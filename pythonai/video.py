import os
import sys
import re
import cv2
import logging
import numpy as np
import subprocess
import json
import shutil
import glob
import requests
import zipfile
import tarfile
import tempfile
import importlib
import importlib.util
import types
import wave
import contextlib
from flask import Flask, request, jsonify
from datetime import datetime
from collections import Counter
from model_download import (
    MODEL_DATA_DIR,
    DOWNLOADED_ONNX_MODEL_PATH,
    DOWNLOADED_FUNASR_MODEL_PATH,
    MODEL_BUNDLE_READY_PATH,
    download_file,
    ensure_model_bundle,
    has_funasr_model_files,
)

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)

BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.getcwd() if getattr(sys, "frozen", False) else os.path.dirname(BASE_DIR)
ONNX_MODEL_PATH = os.path.join(BASE_DIR, "timestamp_crnn_best.onnx")
LOCAL_FUNASR_MODEL_PATH = os.path.join(BASE_DIR, "funasr-paraformer-zh")
NUMBA_CACHE_DIR = os.path.join(PROJECT_ROOT, ".numba_cache")
DEBUG_ROOT = os.path.join(PROJECT_ROOT, "debug_ocr")
DEFAULT_EXTRACT_DIR = os.path.join(PROJECT_ROOT, "log_hunter_extracted")
SUBTITLE_ROOT = os.path.join(PROJECT_ROOT, "log_hunter_subtitles")
IDE_CACHE_PATH = os.path.join(PROJECT_ROOT, ".logagent_ide.json")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.environ.get("LOGCAT_AGENT_OPENAI_MODEL", "gpt-5.5")
OPENAI_PROXY_URL = os.environ.get("OPENAI_PROXY_URL", "http://localhost:7897").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

os.makedirs(DEBUG_ROOT, exist_ok=True)
os.makedirs(SUBTITLE_ROOT, exist_ok=True)
os.makedirs(MODEL_DATA_DIR, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", NUMBA_CACHE_DIR)
os.makedirs(os.environ["NUMBA_CACHE_DIR"], exist_ok=True)

DEVICE = "cpu"
DEFAULT_ALPHABET = "0123456789-: "
DEFAULT_IMG_H = 64
DEFAULT_IMG_W = 512


def ensure_optional_file_from_url(target_path, url_env_name):
    if os.path.exists(target_path):
        return target_path

    url = os.environ.get(url_env_name, "").strip()
    if not url:
        return ""

    download_file(url, target_path)
    return target_path


class OcrRuntime:
    def __init__(self, backend, model_path, alphabet, img_h, img_w, session=None):
        self.backend = backend
        self.model_path = model_path
        self.alphabet = alphabet
        self.img_h = int(img_h)
        self.img_w = int(img_w)
        self.session = session
        self.input_name = session.get_inputs()[0].name if session else ""
        self.output_name = session.get_outputs()[0].name if session else ""

    def predict(self, input_array):
        return self.session.run([self.output_name], {self.input_name: input_array})[0]


def load_ocr_runtime():
    ensure_model_bundle()

    onnx_path = ONNX_MODEL_PATH if os.path.exists(ONNX_MODEL_PATH) else DOWNLOADED_ONNX_MODEL_PATH
    onnx_path = ensure_optional_file_from_url(
        onnx_path,
        "LOGCAT_AGENT_CRNN_ONNX_MODEL_URL",
    )

    if onnx_path:
        try:
            import onnxruntime as ort
        except Exception as e:
            raise RuntimeError(
                "缺少 onnxruntime，请安装 onnxruntime 后再运行 OCR 推理"
            ) from e

        providers = ["CPUExecutionProvider"]
        available_providers = ort.get_available_providers()
        if "CUDAExecutionProvider" in available_providers:
            providers.insert(0, "CUDAExecutionProvider")

        session = ort.InferenceSession(onnx_path, providers=providers)
        logger.info("timestamp_crnn_best.onnx 加载成功: %s", onnx_path)
        return OcrRuntime(
            backend="onnx",
            model_path=onnx_path,
            alphabet=DEFAULT_ALPHABET,
            img_h=DEFAULT_IMG_H,
            img_w=DEFAULT_IMG_W,
            session=session,
        )

    raise FileNotFoundError(
        "缺少 OCR ONNX 模型 timestamp_crnn_best.onnx。请把模型放到 "
        f"{ONNX_MODEL_PATH}，或设置 LOGCAT_AGENT_MODEL_BUNDLE_URL 为包含 OCR 和字幕模型的 zip 地址。"
    )


OCR_RUNTIME = load_ocr_runtime()
ALPHABET = OCR_RUNTIME.alphabet
IMG_H = OCR_RUNTIME.img_h
IMG_W = OCR_RUNTIME.img_w

BLANK_INDEX = 0
INDEX_TO_CHAR = {i + 1: c for i, c in enumerate(ALPHABET)}

logger.info(f"OCR_BACKEND: {OCR_RUNTIME.backend}")
logger.info(f"OCR_MODEL: {OCR_RUNTIME.model_path}")
logger.info(f"DEVICE: {DEVICE}")
logger.info(f"IMG_W: {IMG_W}, IMG_H: {IMG_H}")
logger.info(f"ALPHABET: {ALPHABET}")

FUNASR_MODEL = None
FUNASR_MODEL_PATH = ""


def get_funasr_model():
    global FUNASR_MODEL
    global FUNASR_MODEL_PATH

    if FUNASR_MODEL is not None:
        return FUNASR_MODEL

    Paraformer = load_funasr_paraformer_class()

    env_model_dir = os.environ.get("LOGCAT_AGENT_FUNASR_MODEL_DIR", "").strip()
    if env_model_dir:
        model_dir = env_model_dir
    elif has_funasr_model_files(LOCAL_FUNASR_MODEL_PATH):
        model_dir = LOCAL_FUNASR_MODEL_PATH
    else:
        ensure_model_bundle()
        model_dir = DOWNLOADED_FUNASR_MODEL_PATH

    if not has_funasr_model_files(model_dir):
        raise FileNotFoundError(
            "本地 FunASR 字幕模型不存在。请把模型放到 "
            f"{LOCAL_FUNASR_MODEL_PATH}，或设置 LOGCAT_AGENT_MODEL_BUNDLE_URL "
            "为包含 OCR 和 FunASR 字幕模型的 zip 地址后重启应用。"
        )

    FUNASR_MODEL = Paraformer(
        model_dir,
        batch_size=int(os.environ.get("LOGCAT_AGENT_FUNASR_BATCH_SIZE", "1")),
        quantize=os.environ.get("LOGCAT_AGENT_FUNASR_QUANTIZE", "true").lower()
        not in {"0", "false", "no"},
    )
    FUNASR_MODEL_PATH = model_dir

    logger.info("FunASR Paraformer 加载成功 model=%s", model_dir)

    return FUNASR_MODEL


def load_funasr_paraformer_class():
    try:
        importlib.invalidate_caches()
        if "librosa" not in sys.modules:
            fake_librosa = types.ModuleType("librosa")
            fake_librosa.load = load_wav_for_funasr
            sys.modules["librosa"] = fake_librosa

        package_spec = importlib.util.find_spec("funasr_onnx")
        if package_spec is None or not package_spec.submodule_search_locations:
            raise ImportError("funasr_onnx package not found")

        package_dir = next(iter(package_spec.submodule_search_locations))
        package = sys.modules.get("funasr_onnx")
        if package is None:
            package = types.ModuleType("funasr_onnx")
            package.__path__ = [package_dir]
            package.__package__ = "funasr_onnx"
            sys.modules["funasr_onnx"] = package

        module_name = "funasr_onnx.paraformer_bin"
        module = sys.modules.get(module_name)
        if module is None:
            module_path = os.path.join(package_dir, "paraformer_bin.py")
            module_spec = importlib.util.spec_from_file_location(module_name, module_path)
            if module_spec is None or module_spec.loader is None:
                raise ImportError(f"无法加载 {module_path}")

            module = importlib.util.module_from_spec(module_spec)
            sys.modules[module_name] = module
            module_spec.loader.exec_module(module)

        return module.Paraformer
    except Exception as e:
        raise RuntimeError(
            "缺少 funasr_onnx，请先安装 Python 依赖: pip install funasr-onnx"
        ) from e


def load_wav_for_funasr(path, sr=16000):
    with contextlib.closing(wave.open(path, "rb")) as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise ValueError(f"FunASR 只支持 16-bit PCM wav，当前采样宽度: {sample_width}")

    audio = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)

    if sr and rate != sr:
        raise ValueError(f"FunASR 需要 {sr}Hz wav，当前采样率: {rate}")

    return audio.astype(np.float32) / 32768.0, rate


def normalize_bug_description(segments):
    texts = [
        item.get("text", "").strip()
        for item in segments
        if item.get("text", "").strip()
    ]

    text = "，".join(texts)
    text = re.sub(r"\s+", "", text)
    text = polish_asr_bug_text(text)
    text = re.sub(r"，+", "，", text).strip("，。 ")

    if text and text[-1] not in "。！？!?":
        text += "。"

    return text


CHINESE_NUMERAL_VALUES = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def parse_chinese_number(text):
    if not text:
        return None

    if text in CHINESE_NUMERAL_VALUES:
        return CHINESE_NUMERAL_VALUES[text]

    if "十" in text:
        left, right = text.split("十", 1)
        tens = CHINESE_NUMERAL_VALUES.get(left, 1 if not left else None)
        ones = CHINESE_NUMERAL_VALUES.get(right, 0 if not right else None)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones

    digits = []
    for char in text:
        if char not in CHINESE_NUMERAL_VALUES:
            return None
        digits.append(str(CHINESE_NUMERAL_VALUES[char]))

    return int("".join(digits)) if digits else None


def normalize_spoken_decimal(match):
    integer = parse_chinese_number(match.group(1))
    decimal = parse_chinese_number(match.group(2))

    if integer is None or decimal is None:
        return match.group(0)

    return f"{integer}.{decimal:02d}"


def polish_asr_bug_text(text):
    text = re.sub(r"[嗯啊呃]+", "", text)
    text = re.sub(
        r"([零〇一二两三四五六七八九十]{1,3})点([零〇一二两三四五六七八九十]{1,3})",
        normalize_spoken_decimal,
        text,
    )

    replacements = [
        ("然后切换就会", "然后切换，就会"),
        ("切换就会", "切换，就会"),
        ("卡到", "卡到"),
        ("界面此时", "界面，此时"),
        ("视图需要", "视图，需要"),
        ("重新点击能切换", "重新点击才能切换"),
    ]

    for source, target in replacements:
        text = text.replace(source, target)

    text = re.sub(r"(4\.\d{2})(?=打开)", r"\1，", text)
    text = re.sub(r"(才能切换)(4\.\d{2})", r"\1。\n\2", text)
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


def audio_duration_seconds(audio_path):
    try:
        with contextlib.closing(wave.open(audio_path, "rb")) as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            return frames / float(rate or 1)
    except Exception:
        return 0.0


def normalize_funasr_results(result):
    if isinstance(result, list):
        return result

    if isinstance(result, dict):
        return [result]

    return [{"text": str(result or "")}]


def funasr_sentence_segments(result, duration):
    subtitles = []
    records = normalize_funasr_results(result)

    for record in records:
        if not isinstance(record, dict):
            text = keep_subtitle_display_text(str(record))
            if text:
                subtitles.append({"start": 0.0, "end": round(duration, 3), "text": text})
            continue

        sentence_info = record.get("sentence_info")
        if isinstance(sentence_info, list) and sentence_info:
            for sentence in sentence_info:
                if not isinstance(sentence, dict):
                    continue

                text = keep_subtitle_display_text(sentence.get("text", ""))
                if not text:
                    continue

                start = float(sentence.get("start", 0) or 0) / 1000.0
                end = float(sentence.get("end", 0) or 0) / 1000.0
                if end <= start:
                    end = min(start + 2.0, duration) if duration > 0 else start + 2.0

                subtitles.append({
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": text,
                })

        text = keep_subtitle_display_text(record.get("text", ""))
        if not text:
            preds = record.get("preds")
            if isinstance(preds, (list, tuple)) and preds:
                text = keep_subtitle_display_text(preds[0])
            elif isinstance(preds, str):
                text = keep_subtitle_display_text(preds)

        if text and not subtitles:
            subtitles.append({"start": 0.0, "end": round(duration, 3), "text": text})

    return subtitles


def transcribe_audio(audio_path):
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    model = get_funasr_model()
    duration = audio_duration_seconds(audio_path)
    audio, _ = load_wav_for_funasr(audio_path, sr=16000)
    result = model(
        audio,
        sentence_timestamp=True,
    )
    subtitles = funasr_sentence_segments(result, duration)

    bug_description = normalize_bug_description(subtitles)
    output_path = subtitles_output_path(audio_path)

    payload = {
        "audio_path": audio_path,
        "language": "zh",
        "language_probability": 1.0,
        "asr_backend": "funasr",
        "asr_model": FUNASR_MODEL_PATH,
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
    pred = np.asarray(pred).argmax(2)
    pred = pred[:, 0].tolist()

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

    input_array = img[np.newaxis, np.newaxis, :, :].astype("float32")

    return input_array, gray


def recognize_one_roi(roi):
    input_array, debug_img = preprocess_for_crnn(roi)
    pred = OCR_RUNTIME.predict(input_array)

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


def extract_openai_output_text(payload):
    if not isinstance(payload, dict):
        return ""

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    texts = []

    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue

        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue

            text = content.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())

    return "\n".join(texts).strip()


def format_openai_request_error(error):
    message = str(error)
    hints = []

    if "Network is unreachable" in message or "Failed to establish a new connection" in message:
        hints.append("当前 Python 服务无法连接 OpenAI 地址，通常是机器无外网或没有配置代理")

    if OPENAI_BASE_URL == "https://api.openai.com/v1":
        hints.append("如需走代理或中转服务，请设置环境变量 OPENAI_BASE_URL")

    hints.append("如需走本机代理，请设置 HTTPS_PROXY/HTTP_PROXY 后重启应用")

    return (
        "OpenAI 请求失败\n"
        f"Base URL: {OPENAI_BASE_URL}\n"
        f"Proxy: {OPENAI_PROXY_URL or '(none)'}\n"
        f"异常: {message}\n"
        f"建议: {'；'.join(hints)}"
    )


def read_source_excerpt(file_path, line_no, radius=35):
    if not file_path or not os.path.isfile(file_path):
        return ""

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = list(f)
    except Exception:
        return ""

    target = max(int(line_no or 1), 1)
    start = max(target - radius, 1)
    end = min(target + radius, len(lines))
    excerpt = []

    for current in range(start, end + 1):
        excerpt.append(f"{current}: {lines[current - 1].rstrip()}")

    return "\n".join(excerpt)


def locate_source_context(source_root, log_text):
    root = os.path.abspath(source_root or "")

    if not root or not os.path.isdir(root):
        return {
            "success": False,
            "error": "项目源码目录不存在",
            "source_root": source_root,
        }

    candidates = extract_source_candidates(log_text)
    method_name = extract_method_candidate(log_text)
    log_message = extract_log_message_candidate(log_text)

    for class_name in candidates:
        files = source_file_candidates(root, class_name)

        for file_path in files:
            line_no = find_source_line(file_path, method_name, class_name, log_message)
            return {
                "success": True,
                "source_root": root,
                "class_name": class_name,
                "method_name": method_name,
                "log_message": log_message,
                "file": file_path,
                "line": line_no,
                "excerpt": read_source_excerpt(file_path, line_no),
            }

    return {
        "success": False,
        "error": "未找到对应源码文件",
        "source_root": root,
        "candidates": candidates,
        "method_name": method_name,
        "log_message": log_message,
    }


def analyze_log_flow_with_openai(flow):
    api_key = OPENAI_API_KEY

    if not api_key:
        return {
            "success": False,
            "error": "未设置 OPENAI_API_KEY。请 export OPENAI_API_KEY=你的有效 key 后重启应用/Python 服务。",
        }

    sublime = flow.get("sublime") if isinstance(flow.get("sublime"), dict) else {}
    hit = sublime.get("hit") if isinstance(sublime.get("hit"), dict) else {}
    tag_lines = sublime.get("current_file_tag_lines")
    if not isinstance(tag_lines, list):
        tag_lines = []

    selected_lines = []
    for item in tag_lines[:10]:
        if not isinstance(item, dict):
            continue

        selected_lines.append(
            f"{item.get('line', '')} | {item.get('time', '')} | {item.get('text', '')}"
        )

    voice = flow.get("voice") if isinstance(flow.get("voice"), dict) else {}
    nearby_subtitles = voice.get("nearby_subtitles")
    if not isinstance(nearby_subtitles, list):
        nearby_subtitles = []

    selected_subtitles = []
    for item in nearby_subtitles[:12]:
        if not isinstance(item, dict):
            continue

        selected_subtitles.append(
            f"{item.get('start', '')}-{item.get('end', '')}s | {item.get('text', '')}"
        )

    source_context = locate_source_context(
        flow.get("source_root") or "",
        hit.get("text") or (tag_lines[0].get("text") if tag_lines and isinstance(tag_lines[0], dict) else ""),
    )
    source_excerpt = source_context.get("excerpt") if source_context.get("success") else ""

    system_prompt = (
        "你是车机日志和 Android 源码分析助手。只能基于输入的 10 条日志、语音字幕和源码片段推理，"
        "不能编造输入中没有的事实。回答要直接给出问题总结和可执行解决方案。"
    )
    user_prompt = (
        "请结合下面信息分析问题，输出：\n"
        "1. 问题总结\n"
        "2. 日志证据\n"
        "3. 语音字幕佐证\n"
        "4. 源码关联\n"
        "5. 解决方案\n"
        "6. 置信度\n\n"
        f"Tag: {(flow.get('tag') or '')}\n"
        f"时间戳: {(flow.get('timestamp') or '')}\n"
        f"日志文件: {hit.get('file', '')}\n\n"
        "对应 Tag 的 10 条日志：\n"
        f"{chr(10).join(selected_lines) if selected_lines else '(empty)'}\n\n"
        "语音字幕/Bug描述：\n"
        f"{voice.get('bug_description') or '(empty)'}\n\n"
        "当前时间附近字幕：\n"
        f"{chr(10).join(selected_subtitles) if selected_subtitles else '(empty)'}\n\n"
        "源码定位：\n"
        f"文件: {source_context.get('file', '')}\n"
        f"行号: {source_context.get('line', '')}\n"
        f"类: {source_context.get('class_name', '')}\n"
        f"方法: {source_context.get('method_name', '')}\n"
        f"定位状态: {source_context.get('error', 'success')}\n\n"
        "源码片段：\n"
        f"{source_excerpt if source_excerpt else '(empty)'}\n"
    )

    body = {
        "model": os.environ.get("LOGCAT_AGENT_OPENAI_MODEL", OPENAI_MODEL),
        "instructions": system_prompt,
        "input": user_prompt,
        "max_output_tokens": 700,
    }
    proxies = (
        {
            "http": OPENAI_PROXY_URL,
            "https": OPENAI_PROXY_URL,
        }
        if OPENAI_PROXY_URL
        else None
    )

    try:
        response = requests.post(
            f"{OPENAI_BASE_URL}/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            proxies=proxies,
            timeout=300,
        )
    except Exception as e:
        return {"success": False, "error": format_openai_request_error(e)}

    try:
        payload = response.json()
    except Exception:
        payload = {}

    if response.status_code >= 400:
        message = ""
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            message = payload["error"].get("message") or ""

        return {
            "success": False,
            "error": message or response.text,
            "status_code": response.status_code,
            "model": body["model"],
        }

    analysis = extract_openai_output_text(payload)

    return {
        "success": bool(analysis),
        "analysis": analysis,
        "error": "" if analysis else "OpenAI 返回内容为空",
        "model": body["model"],
    }


def extract_source_candidates(log_text):
    text = log_text or ""
    candidates = []
    log_tag = ""

    tag_match = re.search(
        r"\b[VDIWEAF]\s+([A-Za-z_][A-Za-z0-9_.$]*)\s*:",
        text,
    )
    if tag_match:
        log_tag = tag_match.group(1).strip(".")

    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_.$]*)\s*:", text):
        value = match.group(1).strip(".")
        if not value or value in candidates:
            continue
        if log_tag and value != log_tag and match.start() > tag_match.end():
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


def extract_log_message_candidate(log_text):
    text = log_text or ""
    match = re.search(
        r"\b[VDIWEAF]\s+([A-Za-z_][A-Za-z0-9_.$]*)\s*:\s*(.+)$",
        text,
    )

    if match:
        return match.group(2).strip()

    matches = list(re.finditer(r"\b([A-Za-z_][A-Za-z0-9_.$]*)\s*:\s*", text))
    if not matches:
        return ""

    return text[matches[0].end():].strip()


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


def source_line_text_candidates(log_message):
    text = (log_message or "").strip()
    if not text:
        return []

    candidates = []
    normalized = re.sub(r"\s+", " ", text).strip()
    if normalized:
        candidates.append(normalized)

    # Labels like "dx:", "dy:", "action:" often survive in source log strings
    # even when runtime values are interpolated or concatenated.
    labels = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*[:=]", text)
    label_candidates = []
    for label in labels:
        if label not in label_candidates:
            label_candidates.append(label)

    if label_candidates:
        candidates.append(label_candidates)

    static_parts = [
        item.strip()
        for item in re.split(
            r"[-+]?\d+(?:\.\d+)?|0x[0-9A-Fa-f]+|true|false|null",
            text,
        )
        if len(item.strip()) >= 3
    ]

    for part in static_parts:
        if part not in candidates:
            candidates.append(part)

    return candidates


def find_log_message_line(lines, log_message):
    candidates = source_line_text_candidates(log_message)
    if not candidates:
        return 0

    for candidate in candidates:
        if isinstance(candidate, str):
            for index, line in enumerate(lines, start=1):
                if candidate in line:
                    return index

        if isinstance(candidate, list) and len(candidate) >= 2:
            for index, line in enumerate(lines, start=1):
                if all(label in line for label in candidate):
                    return index

    return 0


def find_source_line(file_path, method_name, class_name, log_message=""):
    line_no = 1

    if not method_name and not class_name and not log_message:
        return line_no

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = list(f)
    except Exception:
        return line_no

    message_line = find_log_message_line(lines, log_message)
    if message_line:
        return message_line

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
    log_message = extract_log_message_candidate(log_text)

    for class_name in candidates:
        files = source_file_candidates(root, class_name)

        for file_path in files:
            line_no = find_source_line(file_path, method_name, class_name, log_message)
            command = open_source_file(file_path, line_no)

            return {
                "success": True,
                "source_root": root,
                "class_name": class_name,
                "method_name": method_name,
                "log_message": log_message,
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
        "log_message": log_message,
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


@app.route("/analyze_log_flow", methods=["POST"])
def analyze_log_flow():
    try:
        payload = request.get_json(silent=True) or {}
        result = analyze_log_flow_with_openai(payload)
        status = 200 if result.get("success") else 400

        return jsonify(result), status

    except Exception as e:
        logger.exception("OpenAI 日志分析接口异常")

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
        "ocr_onnx_model_path": ONNX_MODEL_PATH,
        "ocr_onnx_model_exists": os.path.exists(ONNX_MODEL_PATH),
        "runtime_model_path": OCR_RUNTIME.model_path,
        "runtime_model_exists": os.path.exists(OCR_RUNTIME.model_path),
        "model_data_dir": MODEL_DATA_DIR,
        "local_funasr_model_path": LOCAL_FUNASR_MODEL_PATH,
        "local_funasr_model_exists": has_funasr_model_files(LOCAL_FUNASR_MODEL_PATH),
        "downloaded_funasr_model_path": DOWNLOADED_FUNASR_MODEL_PATH,
        "downloaded_funasr_model_exists": has_funasr_model_files(DOWNLOADED_FUNASR_MODEL_PATH),
        "funasr_model_path": LOCAL_FUNASR_MODEL_PATH if has_funasr_model_files(LOCAL_FUNASR_MODEL_PATH) else DOWNLOADED_FUNASR_MODEL_PATH,
        "funasr_model_exists": has_funasr_model_files(LOCAL_FUNASR_MODEL_PATH) or has_funasr_model_files(DOWNLOADED_FUNASR_MODEL_PATH),
        "asr_backend": "funasr",
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
        host="localhost",
        port=5000,
        debug=False,
    )
