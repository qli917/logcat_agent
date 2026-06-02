import os
import sys
import re
import cv2
import torch
import logging
import numpy as np
import subprocess
import json
import shutil
import glob
from flask import Flask, request, jsonify
from datetime import datetime
from collections import Counter

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

MODEL_PATH = os.path.join(BASE_DIR, "timestamp_crnn_best.pt")
DEFAULT_WHISPER_TURBO_MODEL_PATH = os.path.join(
    BASE_DIR,
    "models",
    "faster-whisper-large-v3-turbo",
)
DEFAULT_WHISPER_MODEL_PATH = os.path.join(BASE_DIR, "models", "faster-whisper-small")
DEBUG_ROOT = os.path.join(BASE_DIR, "debug_ocr")
DEFAULT_EXTRACT_DIR = os.path.join(PROJECT_ROOT, "log_hunter_extracted")
SUBTITLE_ROOT = os.path.join(PROJECT_ROOT, "log_hunter_subtitles")
IDE_CACHE_PATH = os.path.join(PROJECT_ROOT, ".logagent_ide.json")

os.makedirs(DEBUG_ROOT, exist_ok=True)
os.makedirs(SUBTITLE_ROOT, exist_ok=True)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


class CRNN(torch.nn.Module):
    def __init__(self, num_classes):
        super().__init__()

        self.cnn = torch.nn.Sequential(
            torch.nn.Conv2d(1, 64, 3, 1, 1),
            torch.nn.BatchNorm2d(64),
            torch.nn.ReLU(True),
            torch.nn.MaxPool2d(2, 2),

            torch.nn.Conv2d(64, 128, 3, 1, 1),
            torch.nn.BatchNorm2d(128),
            torch.nn.ReLU(True),
            torch.nn.MaxPool2d(2, 2),

            torch.nn.Conv2d(128, 256, 3, 1, 1),
            torch.nn.BatchNorm2d(256),
            torch.nn.ReLU(True),

            torch.nn.Conv2d(256, 256, 3, 1, 1),
            torch.nn.BatchNorm2d(256),
            torch.nn.ReLU(True),
            torch.nn.MaxPool2d((2, 1), (2, 1)),

            torch.nn.Conv2d(256, 512, 3, 1, 1),
            torch.nn.BatchNorm2d(512),
            torch.nn.ReLU(True),

            torch.nn.Conv2d(512, 512, 3, 1, 1),
            torch.nn.BatchNorm2d(512),
            torch.nn.ReLU(True),
            torch.nn.MaxPool2d((2, 1), (2, 1)),
        )

        self.rnn = torch.nn.LSTM(
            input_size=512 * 4,
            hidden_size=256,
            num_layers=2,
            bidirectional=True,
            batch_first=False,
        )

        self.fc = torch.nn.Linear(512, num_classes)

    def forward(self, x):
        conv = self.cnn(x)
        b, c, h, w = conv.size()
        conv = conv.permute(3, 0, 1, 2)
        conv = conv.contiguous().view(w, b, c * h)
        recurrent, _ = self.rnn(conv)
        output = self.fc(recurrent)
        return output


if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"找不到模型文件: {MODEL_PATH}")

checkpoint = torch.load(MODEL_PATH, map_location=DEVICE)

ALPHABET = checkpoint["alphabet"]
IMG_H = checkpoint["img_h"]
IMG_W = checkpoint["img_w"]

BLANK_INDEX = 0
INDEX_TO_CHAR = {i + 1: c for i, c in enumerate(ALPHABET)}

model = CRNN(num_classes=len(ALPHABET) + 1).to(DEVICE)
model.load_state_dict(checkpoint["model"])
model.eval()

logger.info("timestamp_crnn_best.pt 加载成功")
logger.info(f"DEVICE: {DEVICE}")
logger.info(f"IMG_W: {IMG_W}, IMG_H: {IMG_H}")
logger.info(f"ALPHABET: {ALPHABET}")

WHISPER_MODEL = None


def get_whisper_model():
    global WHISPER_MODEL

    if WHISPER_MODEL is not None:
        return WHISPER_MODEL

    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        raise RuntimeError(
            "缺少 faster_whisper，请先安装 Python 依赖: pip install faster-whisper"
        ) from e

    model_size = os.environ.get("LOGCAT_AGENT_WHISPER_MODEL")
    if not model_size:
        if os.path.exists(DEFAULT_WHISPER_TURBO_MODEL_PATH):
            model_size = DEFAULT_WHISPER_TURBO_MODEL_PATH
        elif os.path.exists(DEFAULT_WHISPER_MODEL_PATH):
            model_size = DEFAULT_WHISPER_MODEL_PATH
        else:
            raise FileNotFoundError(
                f"本地 Whisper 模型不存在: {DEFAULT_WHISPER_TURBO_MODEL_PATH} 或 {DEFAULT_WHISPER_MODEL_PATH}"
            )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    WHISPER_MODEL = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
    )

    logger.info(
        "Faster-Whisper 加载成功 model=%s device=%s compute_type=%s",
        model_size,
        device,
        compute_type,
    )

    return WHISPER_MODEL


def normalize_bug_description(segments):
    texts = [
        item.get("text", "").strip()
        for item in segments
        if item.get("text", "").strip()
    ]

    text = "，".join(texts)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"，+", "，", text).strip("，。 ")

    if text and text[-1] not in "。！？!?":
        text += "。"

    return text


def keep_subtitle_display_text(text):
    text = text or ""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9，。！？、：；（）《》“”‘’…,.!?;:()\\[\\]_/\\- +#]", "", text)
    text = re.sub(r"[，。！？、：；,.!?;:]{2,}", lambda m: m.group(0)[0], text)
    return text.strip("，。！？、：；,.!?;: ")


def subtitles_output_path(audio_path):
    base = os.path.splitext(os.path.basename(audio_path))[0]
    return os.path.join(SUBTITLE_ROOT, f"{base}_subtitles.json")


def transcribe_audio(audio_path):
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    model = get_whisper_model()

    segments_iter, info = model.transcribe(
        audio_path,
        language="zh",
        vad_filter=True,
        beam_size=int(os.environ.get("LOGCAT_AGENT_WHISPER_BEAM_SIZE", "5")),
        best_of=int(os.environ.get("LOGCAT_AGENT_WHISPER_BEST_OF", "5")),
        patience=1.2,
        condition_on_previous_text=True,
        initial_prompt="以下是中文车机操作录屏的语音字幕，内容可能包含泊车辅助、摄像机视图、APA、AVM、摄像机、重新电机切换等词。",
    )

    subtitles = []

    for segment in segments_iter:
        text = keep_subtitle_display_text(segment.text)

        if not text:
            continue

        subtitles.append({
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "text": text,
        })

    bug_description = normalize_bug_description(subtitles)
    output_path = subtitles_output_path(audio_path)

    payload = {
        "audio_path": audio_path,
        "language": getattr(info, "language", "zh"),
        "language_probability": round(
            float(getattr(info, "language_probability", 0.0)),
            4,
        ),
        "bug_description": bug_description,
        "subtitles": subtitles,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    payload["subtitles_path"] = output_path

    return payload


def save_image(path, img):
    try:
        cv2.imwrite(path, img)
    except Exception as e:
        logger.warning(f"保存图片失败: {path}, {e}")


def normalize_text(text):
    if not text:
        return ""

    text = text.strip()

    replace_map = {
        "O": "0",
        "o": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "l": "1",
        "|": "1",
        "!": "1",
        "S": "5",
        "s": "5",
        "B": "8",
        ",": ".",
        "_": "-",
    }

    for k, v in replace_map.items():
        text = text.replace(k, v)

    text = re.sub(r"[^0-9:\-.\s]", "", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def parse_timestamp(text):
    text = normalize_text(text)

    patterns = [
        r"(\d{2})[-.\s]?(\d{2})\s+(\d{2})[:.\s]?(\d{2})[:.\s]?(\d{2})",
        r"(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)
        if not m:
            continue

        month = m.group(1)
        day = m.group(2)
        hour = m.group(3)
        minute = m.group(4)
        second = m.group(5)

        try:
            datetime(
                2026,
                int(month),
                int(day),
                int(hour),
                int(minute),
                int(second),
            )
            return f"{month}-{day} {hour}:{minute}:{second}"
        except Exception:
            continue

    return None


def decode_prediction(pred):
    pred = pred.argmax(2)
    pred = pred[:, 0].detach().cpu().numpy().tolist()

    result = []
    last = BLANK_INDEX

    for i in pred:
        if i != BLANK_INDEX and i != last:
            result.append(INDEX_TO_CHAR.get(i, ""))
        last = i

    return "".join(result)


def build_yellow_mask(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    hsv_mask = cv2.inRange(
        hsv,
        np.array([12, 35, 80]),
        np.array([70, 255, 255]),
    )

    b, g, r = cv2.split(frame)

    bgr_mask = (
        (r > 110)
        & (g > 110)
        & (b < 210)
        & ((r.astype(np.int16) + g.astype(np.int16)) > (b.astype(np.int16) * 2))
    ).astype(np.uint8) * 255

    mask = cv2.bitwise_or(hsv_mask, bgr_mask)

    kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_small, iterations=1)

    kernel_line = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_line, iterations=2)

    return mask


def get_candidate_rois(frame):
    h, w = frame.shape[:2]

    mask = build_yellow_mask(frame)

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    candidates = []

    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)

        area = bw * bh
        ratio = bw / max(bh, 1)

        if bw < int(w * 0.14):
            continue
        if bh < int(h * 0.020):
            continue
        if ratio < 3.0:
            continue
        if area < 600:
            continue
        if bh > int(h * 0.25):
            continue

        pad_x = 28
        pad_y = 16

        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(w, x + bw + pad_x)
        y2 = min(h, y + bh + pad_y)

        roi = frame[y1:y2, x1:x2]

        if roi.size == 0:
            continue

        rh, rw = roi.shape[:2]

        if rw / max(rh, 1) < 3.0:
            continue

        score = bw * 2 + ratio * 30 + area * 0.01

        candidates.append({
            "score": score,
            "roi": roi,
            "box": (x1, y1, x2, y2),
        })

    candidates.sort(key=lambda item: item["score"], reverse=True)

    return candidates, mask


def preprocess_for_crnn(roi):
    roi = cv2.resize(
        roi,
        None,
        fx=2.0,
        fy=2.0,
        interpolation=cv2.INTER_CUBIC,
    )

    roi = cv2.copyMakeBorder(
        roi,
        8,
        8,
        8,
        8,
        cv2.BORDER_CONSTANT,
        value=[255, 255, 255],
    )

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (IMG_W, IMG_H))

    img = gray.astype("float32") / 255.0
    img = (img - 0.5) / 0.5

    tensor = torch.tensor(img).unsqueeze(0).unsqueeze(0)

    return tensor.to(DEVICE), gray


def recognize_one_roi(roi):
    tensor, debug_img = preprocess_for_crnn(roi)

    with torch.no_grad():
        pred = model(tensor)

    raw = decode_prediction(pred)
    parsed = parse_timestamp(raw)

    return raw, parsed, debug_img


def recognize_frame(frame, debug_dir, name_prefix):
    candidates, mask = get_candidate_rois(frame)

    save_image(os.path.join(debug_dir, f"{name_prefix}_mask.jpg"), mask)

    results = []

    for index, item in enumerate(candidates[:8]):
        roi = item["roi"]

        raw, parsed, debug_img = recognize_one_roi(roi)

        save_image(os.path.join(debug_dir, f"{name_prefix}_roi_{index}.jpg"), roi)
        save_image(os.path.join(debug_dir, f"{name_prefix}_input_{index}.jpg"), debug_img)

        results.append({
            "index": index,
            "raw": raw,
            "parsed": parsed,
            "box": item["box"],
        })

        if parsed:
            return parsed, raw, results

    return None, "", results


def recognize_video(video_path, base_time_ms):
    debug_dir = os.path.join(
        DEBUG_ROOT,
        datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
    )

    os.makedirs(debug_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        return None, {
            "error": "Failed to open video",
            "debug_dir": debug_dir,
        }

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        offsets = [-300, -200, -100, 0, 100, 200, 300]

        all_results = []
        parsed_items = []

        for offset in offsets:
            target_ms = max(0, base_time_ms + offset)
            frame_index = int((target_ms / 1000.0) * fps)

            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

            ret, frame = cap.read()

            if not ret:
                continue

            parsed, raw, frame_results = recognize_frame(
                frame,
                debug_dir,
                f"{offset}",
            )

            all_results.append({
                "offset": offset,
                "raw": raw,
                "parsed": parsed,
                "candidates": frame_results,
            })

            if parsed:
                parsed_items.append(parsed)

        if parsed_items:
            counter = Counter(parsed_items)
            final_timestamp = counter.most_common(1)[0][0]

            return final_timestamp, {
                "mode": "crnn_mmdd_hhmmss_vote",
                "debug_dir": debug_dir,
                "timestamp": final_timestamp,
                "parsed_items": parsed_items,
                "results": all_results,
            }

        return None, {
            "error": "No timestamp parsed",
            "debug_dir": debug_dir,
            "parsed_items": parsed_items,
            "results": all_results,
        }

    finally:
        cap.release()


def normalize_tag(tag):
    return (tag or "").strip().rstrip("_:").lower()


def line_contains_tag(line, tag):
    tag = normalize_tag(tag)

    if not tag:
        return True

    return tag in line.lower()


def parse_target_datetime(timestamp):
    timestamp = (timestamp or "").strip()

    for p in [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ]:
        try:
            return datetime.strptime(timestamp, p)
        except Exception:
            pass

    try:
        return datetime.strptime(
            "2026-" + timestamp,
            "%Y-%m-%d %H:%M:%S",
        )
    except Exception:
        return None


def normalize_time_key(timestamp):
    dt = parse_target_datetime(timestamp)

    if dt:
        return dt.strftime("%m-%d %H:%M:%S")

    timestamp = (timestamp or "").strip()

    if len(timestamp) >= 19 and timestamp[4] == "-":
        return timestamp[5:19]

    if len(timestamp) >= 14:
        return timestamp[:14]

    return timestamp


def parse_time_from_filename(path):
    name = os.path.basename(path)

    m = re.search(r"(\d{14})", name)

    if not m:
        return None

    try:
        return datetime.strptime(
            m.group(1),
            "%Y%m%d%H%M%S",
        )
    except Exception:
        return None


def extract_line_datetime(line):
    m = re.search(
        r"(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
        line,
    )

    if not m:
        return None

    try:
        return datetime.strptime(
            "2026-" + m.group(1),
            "%Y-%m-%d %H:%M:%S",
        )
    except Exception:
        return None


def resolve_log_dir(log_dir):
    log_dir = (log_dir or "").strip()

    if not log_dir:
        return DEFAULT_EXTRACT_DIR

    if os.path.isabs(log_dir):
        return log_dir

    return os.path.join(DEFAULT_EXTRACT_DIR, log_dir)


def is_log_file(path):
    name = os.path.basename(path).lower()

    if not os.path.isfile(path):
        return False

    if not name.startswith("main_log"):
        return False

    bad_exts = [
        ".zip",
        ".tar",
        ".lz4",
        ".done",
        ".db",
        ".md",
    ]

    return not any(name.endswith(ext) for ext in bad_exts)


def collect_log_files(log_dir):
    result = []

    for root, _, files in os.walk(log_dir):
        for name in files:
            path = os.path.join(root, name)

            if is_log_file(path):
                result.append(path)

    result.sort()

    return result


def choose_nearest_files(files, target_dt, limit=3):
    items = []

    for path in files:
        file_dt = parse_time_from_filename(path)

        if file_dt:
            diff = abs((file_dt - target_dt).total_seconds())
        else:
            diff = 999999999

        items.append((diff, path))

    items.sort(key=lambda x: x[0])

    return [path for _, path in items[:limit]]


def search_exact_time_and_tag(files, time_key, tag):
    last_hit = None

    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, start=1):
                    if time_key in line and line_contains_tag(line, tag):
                        last_hit = {
                            "file": path,
                            "line": line_no,
                            "text": line.rstrip(),
                            "mode": "time + tag",
                        }
        except Exception:
            continue

    return last_hit


def search_exact_time(files, time_key):
    last_hit = None

    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, start=1):
                    if time_key in line:
                        last_hit = {
                            "file": path,
                            "line": line_no,
                            "text": line.rstrip(),
                            "mode": "time",
                        }
        except Exception:
            continue

    return last_hit


def search_closest_tag(files, target_dt, tag):
    best_hit = None
    best_diff = 999999999
    fallback = None

    for path in files:
        current_dt = None

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, start=1):
                    dt = extract_line_datetime(line)

                    if dt:
                        current_dt = dt

                    if not line_contains_tag(line, tag):
                        continue

                    fallback = {
                        "file": path,
                        "line": line_no,
                        "text": line.rstrip(),
                        "mode": "tag fallback",
                    }

                    if current_dt:
                        diff = abs((current_dt - target_dt).total_seconds())

                        if diff <= best_diff:
                            best_diff = diff
                            best_hit = {
                                "file": path,
                                "line": line_no,
                                "text": line.rstrip(),
                                "mode": "closest tag",
                            }

        except Exception:
            continue

    return best_hit or fallback


def search_closest_time(files, target_dt):
    best_hit = None
    best_diff = 999999999

    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, start=1):
                    dt = extract_line_datetime(line)

                    if not dt:
                        continue

                    diff = abs((dt - target_dt).total_seconds())

                    if diff <= best_diff:
                        best_diff = diff
                        best_hit = {
                            "file": path,
                            "line": line_no,
                            "text": line.rstrip(),
                            "mode": "closest time",
                        }

        except Exception:
            continue

    return best_hit


def collect_current_file_tag_lines(path, tag, center_line=None, limit=120):
    if not path or not os.path.isfile(path):
        return []

    if not tag or not tag.strip():
        return []

    items = []

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, start=1):
                if not line_contains_tag(line, tag):
                    continue

                dt = extract_line_datetime(line)

                items.append({
                    "line": line_no,
                    "time": dt.strftime("%m-%d %H:%M:%S") if dt else "",
                    "text": line.rstrip(),
                    "distance": abs(line_no - center_line) if center_line else line_no,
                })
    except Exception:
        return []

    items.sort(key=lambda item: item["distance"])
    selected = items[:limit]
    selected.sort(key=lambda item: item["line"])

    return selected


def open_sublime_hit(hit):
    subl = shutil.which("subl") or "/usr/bin/subl"

    if not os.path.exists(subl):
        raise FileNotFoundError("找不到 subl 命令，请确认 Sublime Text 命令行工具已安装")

    subprocess.Popen([
        subl,
        f"{hit['file']}:{hit['line']}",
    ])


def extract_source_candidates(log_text):
    text = log_text or ""
    candidates = []

    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_.$]*)\s*:", text):
        value = match.group(1).strip(".")
        if not value or value in candidates:
            continue

        candidates.append(value)

        if "_" in value:
            suffix = value.split("_")[-1]
            if suffix and suffix not in candidates:
                candidates.append(suffix)

    return candidates


def extract_method_candidate(log_text):
    match = re.search(r":\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", log_text or "")
    return match.group(1) if match else ""


def source_file_candidates(root, class_name):
    source_exts = (".kt", ".java", ".aidl")
    ignored_dirs = {
        ".git",
        ".gradle",
        ".idea",
        "build",
        ".dart_tool",
        "node_modules",
        "log_hunter_extracted",
        "log_hunter_subtitles",
    }
    exact_names = {f"{class_name}{ext}" for ext in source_exts}
    matches = []

    for current_root, dirs, files in os.walk(root):
        dirs[:] = [
            item
            for item in dirs
            if item not in ignored_dirs and not item.startswith(".")
        ]

        for name in files:
            if name in exact_names:
                return [os.path.join(current_root, name)]

            if name.endswith(source_exts) and class_name in name:
                matches.append(os.path.join(current_root, name))

    return matches


def find_source_line(file_path, method_name, class_name):
    line_no = 1

    if not method_name and not class_name:
        return line_no

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = list(f)
    except Exception:
        return line_no

    if method_name:
        method_pattern = re.compile(
            r"\b(fun|void|boolean|int|long|float|double|String|public|private|protected|static|final|override)\b.*\b"
            + re.escape(method_name)
            + r"\s*\("
        )
        for index, line in enumerate(lines, start=1):
            if method_pattern.search(line) or re.search(
                r"\b" + re.escape(method_name) + r"\s*\(",
                line,
            ):
                return index

    if class_name:
        class_pattern = re.compile(
            r"\b(class|object|interface|enum)\s+"
            + re.escape(class_name)
            + r"\b"
        )
        for index, line in enumerate(lines, start=1):
            if class_pattern.search(line):
                return index

    return line_no


def existing_command_candidates(candidates):
    commands = []

    for candidate in candidates:
        if not candidate:
            continue

        resolved = (
            shutil.which(candidate)
            if os.path.basename(candidate) == candidate
            else candidate
        )

        if resolved and os.path.exists(resolved) and os.access(resolved, os.X_OK):
            if resolved not in commands:
                commands.append(resolved)

    return commands


def read_ide_cache():
    try:
        with open(IDE_CACHE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)

        command = payload.get("command")

        if (
            command
            and os.path.exists(command)
            and os.access(command, os.X_OK)
        ):
            return command
    except Exception:
        return None

    return None


def write_ide_cache(command):
    try:
        with open(IDE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "command": command,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception:
        logger.exception("写入 IDE 路径缓存失败")


def scan_android_studio_installations():
    home = os.path.expanduser("~")
    patterns = [
        os.path.join(home, "android", "android-studio*", "android-studio", "bin", "studio.sh"),
        os.path.join(home, "android", "android-studio*", "android-studio", "bin", "studio"),
        os.path.join(home, "Android", "android-studio*", "bin", "studio.sh"),
        os.path.join(home, "Android", "android-studio*", "bin", "studio"),
        os.path.join(home, "android-studio*", "bin", "studio.sh"),
        os.path.join(home, "android-studio*", "bin", "studio"),
        "/opt/android-studio*/bin/studio.sh",
        "/opt/android-studio*/bin/studio",
        "/usr/local/android-studio*/bin/studio.sh",
        "/usr/local/android-studio*/bin/studio",
        "/snap/bin/android-studio",
        "/var/lib/flatpak/exports/bin/com.google.AndroidStudio",
        os.path.join(home, ".local", "share", "flatpak", "exports", "bin", "com.google.AndroidStudio"),
    ]

    candidates = []

    for pattern in patterns:
        candidates.extend(glob.glob(pattern))

    return sorted(set(candidates))


def android_studio_commands():
    configured = os.environ.get("LOGCAT_AGENT_ANDROID_STUDIO_CMD") or os.environ.get(
        "ANDROID_STUDIO_CMD"
    )

    cached = read_ide_cache()
    commands = existing_command_candidates(
        [
            configured,
            cached,
            "studio",
            "studio.sh",
            "android-studio",
            "idea",
            "idea.sh",
            "/usr/local/bin/studio",
            "/opt/android-studio/bin/studio.sh",
            "/opt/android-studio/bin/studio",
            os.path.expanduser("~/android-studio/bin/studio.sh"),
        ]
        + scan_android_studio_installations()
    )

    if commands:
        write_ide_cache(commands[0])

    return commands


def open_source_file(file_path, line_no):
    commands = android_studio_commands()

    if commands:
        subprocess.Popen([commands[0], "--line", str(max(line_no, 1)), file_path])
        return commands[0]

    raise FileNotFoundError(
        "找不到 Android Studio/IDEA 命令行工具。请在 Android Studio 里创建 Command-line Launcher，"
        "或设置环境变量 LOGCAT_AGENT_ANDROID_STUDIO_CMD=/path/to/studio.sh"
    )


def locate_and_open_source(source_root, log_text):
    root = os.path.abspath(source_root or "")

    if not root or not os.path.isdir(root):
        return {
            "success": False,
            "error": "项目源码目录不存在",
            "source_root": source_root,
        }

    candidates = extract_source_candidates(log_text)
    method_name = extract_method_candidate(log_text)

    for class_name in candidates:
        files = source_file_candidates(root, class_name)

        for file_path in files:
            line_no = find_source_line(file_path, method_name, class_name)
            command = open_source_file(file_path, line_no)

            return {
                "success": True,
                "source_root": root,
                "class_name": class_name,
                "method_name": method_name,
                "file": file_path,
                "line": line_no,
                "command": command,
            }

    return {
        "success": False,
        "error": "未找到对应源码文件",
        "source_root": root,
        "candidates": candidates,
        "method_name": method_name,
    }


def call_sublime_plugin(timestamp, tag="", log_dir=""):
    try:
        real_log_dir = resolve_log_dir(log_dir)
        target_dt = parse_target_datetime(timestamp)
        time_key = normalize_time_key(timestamp)

        if not target_dt:
            return {
                "success": False,
                "error": f"无法解析时间戳: {timestamp}",
            }

        if not os.path.isdir(real_log_dir):
            return {
                "success": False,
                "error": f"日志目录不存在: {real_log_dir}",
            }

        all_files = collect_log_files(real_log_dir)

        if not all_files:
            return {
                "success": False,
                "error": f"没有找到 main_log 文件: {real_log_dir}",
            }

        files = choose_nearest_files(
            all_files,
            target_dt,
            limit=3,
        )

        hit = None

        if tag and tag.strip():
            hit = search_exact_time_and_tag(
                files,
                time_key,
                tag,
            )

            if not hit:
                hit = search_closest_tag(
                    files,
                    target_dt,
                    tag,
                )
        else:
            hit = search_exact_time(
                files,
                time_key,
            )

            if not hit:
                hit = search_closest_time(
                    files,
                    target_dt,
                )

        if not hit:
            return {
                "success": False,
                "error": "未找到匹配日志",
                "timestamp": timestamp,
                "time_key": time_key,
                "tag": tag,
                "log_dir": real_log_dir,
                "files": files,
            }

        tag_lines = collect_current_file_tag_lines(
            hit.get("file"),
            tag,
            center_line=hit.get("line"),
        )

        open_sublime_hit(hit)

        return {
            "success": True,
            "timestamp": timestamp,
            "time_key": time_key,
            "tag": tag,
            "log_dir": real_log_dir,
            "hit": hit,
            "files": files,
            "current_file_tag_lines": tag_lines,
            "current_file_tag_total": len(tag_lines),
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@app.route("/ocr", methods=["GET"])
def extract_timestamp():
    try:
        video_path = request.args.get("path")
        base_time_ms = float(request.args.get("time", 0))

        tag = request.args.get("tag", "")
        log_dir = request.args.get("log_dir", "")

        if not video_path:
            return jsonify({"error": "missing path"}), 400

        if not os.path.exists(video_path):
            return jsonify({
                "error": "video path not exists",
                "path": video_path,
            }), 400

        timestamp, info = recognize_video(
            video_path=video_path,
            base_time_ms=base_time_ms,
        )

        if timestamp:
            if request.args.get("search", "1") == "0":
                return jsonify({
                    "timestamp": timestamp,
                    "mode": info.get("mode"),
                    "debug_dir": info.get("debug_dir"),
                    "parsed_items": info.get("parsed_items"),
                    "results": info.get("results"),
                }), 200

            sublime_result = call_sublime_plugin(
                timestamp=timestamp,
                tag=tag,
                log_dir=log_dir,
            )

            return jsonify({
                "timestamp": timestamp,
                "mode": info.get("mode"),
                "debug_dir": info.get("debug_dir"),
                "parsed_items": info.get("parsed_items"),
                "results": info.get("results"),
                "sublime": sublime_result,
            }), 200

        return jsonify({
            "error": info.get("error", "No match"),
            "debug_dir": info.get("debug_dir"),
            "parsed_items": info.get("parsed_items"),
            "results": info.get("results"),
        }), 404

    except Exception as e:
        logger.exception("OCR接口异常")

        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
        }), 500


@app.route("/open_log_hit", methods=["POST"])
def open_log_hit():
    try:
        payload = request.get_json(silent=True) or {}
        file_path = (payload.get("file") or "").strip()
        line = int(payload.get("line") or 1)

        if not file_path:
            return jsonify({"error": "missing file"}), 400

        if not os.path.exists(file_path):
            return jsonify({
                "error": "file not exists",
                "file": file_path,
            }), 400

        open_sublime_hit({
            "file": file_path,
            "line": max(line, 1),
        })

        return jsonify({
            "success": True,
            "file": file_path,
            "line": max(line, 1),
        }), 200

    except Exception as e:
        logger.exception("打开 Sublime 接口异常")

        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
        }), 500


@app.route("/open_source_hit", methods=["POST"])
def open_source_hit():
    try:
        payload = request.get_json(silent=True) or {}
        source_root = (payload.get("source_root") or "").strip()
        log_text = (payload.get("text") or "").strip()

        if not log_text:
            return jsonify({"error": "missing text"}), 400

        result = locate_and_open_source(source_root, log_text)
        status = 200 if result.get("success") else 404

        return jsonify(result), status

    except Exception as e:
        logger.exception("打开源码接口异常")

        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
        }), 500


@app.route("/open_by_timestamp", methods=["POST"])
def open_by_timestamp():
    try:
        payload = request.get_json(silent=True) or {}
        timestamp = (payload.get("timestamp") or "").strip()
        tag = (payload.get("tag") or "").strip()
        log_dir = (payload.get("log_dir") or "").strip()

        if not timestamp:
            return jsonify({"error": "missing timestamp"}), 400

        result = call_sublime_plugin(
            timestamp=timestamp,
            tag=tag,
            log_dir=log_dir,
        )

        if isinstance(result, dict):
            result.pop("current_file_tag_lines", None)
            result.pop("current_file_tag_total", None)

        status = 200 if result.get("success") else 404

        return jsonify(result), status

    except Exception as e:
        logger.exception("按时间戳打开 Sublime 接口异常")

        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
        }), 500


@app.route("/transcribe", methods=["GET"])
def transcribe_subtitles():
    try:
        audio_path = request.args.get("audio_path", "")

        if not audio_path:
            return jsonify({"error": "missing audio_path"}), 400

        payload = transcribe_audio(audio_path)

        return jsonify(payload), 200

    except Exception as e:
        logger.exception("语音识别接口异常")

        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
        }), 500


@app.route("/debug_path", methods=["GET"])
def debug_path():
    return jsonify({
        "base_dir": BASE_DIR,
        "project_root": PROJECT_ROOT,
        "debug_root": DEBUG_ROOT,
        "default_extract_dir": DEFAULT_EXTRACT_DIR,
        "subtitle_root": SUBTITLE_ROOT,
        "model_path": MODEL_PATH,
        "model_exists": os.path.exists(MODEL_PATH),
        "ide_cache_path": IDE_CACHE_PATH,
        "android_studio_commands": android_studio_commands(),
        "device": DEVICE,
        "img_w": IMG_W,
        "img_h": IMG_H,
        "alphabet": ALPHABET,
        "label_format": "MM-DD HH:MM:SS",
    })


if __name__ == "__main__":
    import logging as flask_logging

    flask_logging.getLogger("werkzeug").setLevel(logging.ERROR)
    ide_commands = android_studio_commands()

    if ide_commands:
        logger.info("Android Studio 命令已发现: %s", ide_commands[0])
    else:
        logger.warning("未发现 Android Studio/IDEA 命令行工具")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
    )
