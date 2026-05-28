import os
import sys
import re
import cv2
import torch
import logging
import numpy as np
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

MODEL_PATH = os.path.join(BASE_DIR, "timestamp_crnn_best.pt")
DEBUG_ROOT = os.path.join(BASE_DIR, "debug_ocr")

os.makedirs(DEBUG_ROOT, exist_ok=True)

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

checkpoint = torch.load(
    MODEL_PATH,
    map_location=DEVICE,
)

ALPHABET = checkpoint["alphabet"]
IMG_H = checkpoint["img_h"]
IMG_W = checkpoint["img_w"]

BLANK_INDEX = 0

INDEX_TO_CHAR = {
    i + 1: c
    for i, c in enumerate(ALPHABET)
}

model = CRNN(
    num_classes=len(ALPHABET) + 1
).to(DEVICE)

model.load_state_dict(checkpoint["model"])
model.eval()

logger.info("timestamp_crnn_best.pt 加载成功")
logger.info(f"DEVICE: {DEVICE}")
logger.info(f"IMG_W: {IMG_W}, IMG_H: {IMG_H}")
logger.info(f"ALPHABET: {ALPHABET}")


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
    """
    新模型格式：
    05-07 16:46:59

    返回：
    05-07 16:46:59
    """
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
            result.append(
                INDEX_TO_CHAR.get(i, "")
            )

        last = i

    return "".join(result)


def build_yellow_mask(frame):
    hsv = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2HSV,
    )

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
        & (
            (r.astype(np.int16) + g.astype(np.int16))
            > (b.astype(np.int16) * 2)
        )
    ).astype(np.uint8) * 255

    mask = cv2.bitwise_or(
        hsv_mask,
        bgr_mask,
    )

    kernel_small = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (3, 3),
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        kernel_small,
        iterations=1,
    )

    kernel_line = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (21, 3),
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        kernel_line,
        iterations=2,
    )

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

        score = (
            bw * 2
            + ratio * 30
            + area * 0.01
        )

        candidates.append({
            "score": score,
            "roi": roi,
            "box": (x1, y1, x2, y2),
        })

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

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

    gray = cv2.cvtColor(
        roi,
        cv2.COLOR_BGR2GRAY,
    )

    gray = cv2.resize(
        gray,
        (IMG_W, IMG_H),
    )

    img = gray.astype("float32") / 255.0
    img = (img - 0.5) / 0.5

    tensor = torch.tensor(
        img
    ).unsqueeze(0).unsqueeze(0)

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

    save_image(
        os.path.join(debug_dir, f"{name_prefix}_mask.jpg"),
        mask,
    )

    results = []

    for index, item in enumerate(candidates[:8]):
        roi = item["roi"]

        raw, parsed, debug_img = recognize_one_roi(roi)

        save_image(
            os.path.join(debug_dir, f"{name_prefix}_roi_{index}.jpg"),
            roi,
        )

        save_image(
            os.path.join(debug_dir, f"{name_prefix}_input_{index}.jpg"),
            debug_img,
        )

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

        offsets = [
            -300,
            -200,
            -100,
            0,
            100,
            200,
            300,
        ]

        all_results = []
        parsed_items = []

        for offset in offsets:
            target_ms = max(
                0,
                base_time_ms + offset,
            )

            frame_index = int(
                (target_ms / 1000.0) * fps
            )

            cap.set(
                cv2.CAP_PROP_POS_FRAMES,
                frame_index,
            )

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
            # 多帧投票
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

@app.route("/ocr", methods=["GET"])
def extract_timestamp():
    try:
        video_path = request.args.get("path")
        base_time_ms = float(
            request.args.get("time", 0)
        )

        if not video_path:
            return jsonify({
                "error": "missing path"
            }), 400

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
            return jsonify({
                "timestamp": timestamp,
                "mode": info.get("mode"),
                "debug_dir": info.get("debug_dir"),
                "parsed_items": info.get("parsed_items"),
                "results": info.get("results"),
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

@app.route("/debug_path", methods=["GET"])
def debug_path():
    return jsonify({
        "base_dir": BASE_DIR,
        "debug_root": DEBUG_ROOT,
        "model_path": MODEL_PATH,
        "model_exists": os.path.exists(MODEL_PATH),
        "device": DEVICE,
        "img_w": IMG_W,
        "img_h": IMG_H,
        "alphabet": ALPHABET,
        "label_format": "MM-DD HH:MM:SS",
    })


if __name__ == "__main__":
    import logging as flask_logging

    flask_logging.getLogger(
        "werkzeug"
    ).setLevel(
        logging.ERROR
    )

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
    )