import os
import sys
import cv2
import csv
import re
import logging
import numpy as np
from flask import Flask, request, jsonify
from datetime import datetime, timedelta

try:
    from paddleocr import PaddleOCR
except Exception:
    PaddleOCR = None

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    stream=sys.stderr
)

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEBUG_ROOT = os.path.join(BASE_DIR, "debug_ocr")
DATASET_ROOT = os.path.join(DEBUG_ROOT, "roi_dataset")
IMAGE_DIR = os.path.join(DATASET_ROOT, "images")
REJECT_DIR = os.path.join(DATASET_ROOT, "reject")
MASK_DIR = os.path.join(DATASET_ROOT, "mask_debug")
LABEL_CSV = os.path.join(DATASET_ROOT, "labels.csv")

for path in [DEBUG_ROOT, DATASET_ROOT, IMAGE_DIR, REJECT_DIR, MASK_DIR]:
    os.makedirs(path, exist_ok=True)

if not os.path.exists(LABEL_CSV):
    with open(LABEL_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["image", "label"])

BASE_TIMESTAMP = datetime.strptime(
    "2026-05-07 16:46:37.190",
    "%Y-%m-%d %H:%M:%S.%f"
)

ocr = None
if PaddleOCR is not None:
    try:
        ocr = PaddleOCR(lang="en", use_textline_orientation=True)
        logger.info("PaddleOCR loaded")
    except Exception as e:
        logger.warning(f"PaddleOCR 初始化失败: {e}")
        ocr = None


def ensure_label_csv():
    if not os.path.exists(LABEL_CSV):
        with open(LABEL_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["image", "label"])


def make_label_from_video_time(time_ms):
    dt = BASE_TIMESTAMP + timedelta(milliseconds=int(time_ms))
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def save_label(image_name, label):
    ensure_label_csv()

    with open(LABEL_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([image_name, label])


def clean_text(text):
    if not text:
        return ""

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


def is_timestamp_text(text):
    text = clean_text(text)

    patterns = [
        r"\d{4}[-.\s]?\d{2}[-.\s]?\d{2}\s+\d{2}[:.\s]?\d{2}[:.\s]?\d{2}(?:[.:]\d{1,3})?",
        r"\d{4}[-.\s]?\d{2}[-.\s]?\d{2}.*?\d{2}[:.\s]?\d{2}[:.\s]?\d{2}",
        r"\d{8}.*?\d{6}",
    ]

    for p in patterns:
        if re.search(p, text):
            return True

    digits = re.sub(r"\D", "", text)

    if len(digits) >= 14 and digits.startswith("202"):
        return True

    return False


def extract_paddle_text(result):
    texts = []

    if result is None:
        return ""

    try:
        for page in result:
            if page is None:
                continue

            if isinstance(page, dict):
                if "rec_texts" in page:
                    texts.extend(page["rec_texts"])
                elif "text" in page:
                    texts.append(page["text"])
                continue

            if isinstance(page, list):
                for line in page:
                    if line is None:
                        continue

                    if isinstance(line, dict):
                        if "text" in line:
                            texts.append(line["text"])
                        elif "rec_text" in line:
                            texts.append(line["rec_text"])
                        continue

                    if isinstance(line, (list, tuple)):
                        if len(line) >= 2:
                            data = line[1]
                            if isinstance(data, (list, tuple)) and len(data) > 0:
                                texts.append(str(data[0]))
                            else:
                                texts.append(str(data))
    except Exception:
        pass

    return " ".join(texts)


def validate_timestamp_roi(roi):
    if ocr is None:
        return False, ""

    try:
        img = cv2.resize(
            roi,
            None,
            fx=2.0,
            fy=2.0,
            interpolation=cv2.INTER_CUBIC
        )

        result = ocr.ocr(img)
        raw = extract_paddle_text(result)
        ok = is_timestamp_text(raw)

        return ok, raw

    except Exception as e:
        logger.warning(f"OCR 验证失败: {e}")
        return False, ""


def build_yellow_mask(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    hsv_mask = cv2.inRange(
        hsv,
        np.array([12, 35, 80]),
        np.array([70, 255, 255])
    )

    b, g, r = cv2.split(frame)

    bgr_mask = (
        (r > 110) &
        (g > 110) &
        (b < 210) &
        ((r.astype(np.int16) + g.astype(np.int16)) > (b.astype(np.int16) * 2))
    ).astype(np.uint8) * 255

    mask = cv2.bitwise_or(hsv_mask, bgr_mask)

    kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_small, iterations=1)

    kernel_line = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_line, iterations=2)

    return mask


def get_candidate_boxes(frame, mask):
    h, w = frame.shape[:2]

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    candidates = []

    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        area = bw * bh
        ratio = bw / max(bh, 1)

        if bw < int(w * 0.18):
            continue

        if bh < int(h * 0.025):
            continue

        if ratio < 4.5:
            continue

        if area < 1000:
            continue

        if bh > int(h * 0.20):
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

        if rw / max(rh, 1) < 4:
            continue

        score = bw * 2 + ratio * 30 + area * 0.01

        candidates.append({
            "score": score,
            "box": (x1, y1, x2, y2),
            "roi": roi,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    return candidates


def crop_timestamp_by_format(frame, frame_index=None):
    mask = build_yellow_mask(frame)

    if frame_index is not None and frame_index % 100 == 0:
        cv2.imwrite(
            os.path.join(MASK_DIR, f"mask_frame_{frame_index:08d}.jpg"),
            mask
        )

    candidates = get_candidate_boxes(frame, mask)

    for item in candidates[:10]:
        roi = item["roi"]

        ok, raw = validate_timestamp_roi(roi)

        if ok:
            logger.info(f"时间戳ROI命中: raw={raw}")
            return roi

    return None


def detect_timestamp(frame, frame_index=None):
    roi = crop_timestamp_by_format(frame, frame_index)

    if roi is None or roi.size == 0:
        return None

    return roi


def save_reject_frame(frame, video_path, frame_index):
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    image_name = f"{video_name}_reject_frame_{frame_index:08d}.jpg"
    image_path = os.path.join(REJECT_DIR, image_name)
    cv2.imwrite(image_path, frame)


def save_roi_image(roi, video_path, time_ms, frame_index):
    video_name = os.path.splitext(os.path.basename(video_path))[0]

    image_name = (
        f"{video_name}_"
        f"frame_{frame_index:08d}_"
        f"{int(time_ms)}ms.png"
    )

    image_path = os.path.join(IMAGE_DIR, image_name)

    if os.path.exists(image_path):
        return image_path, make_label_from_video_time(time_ms)

    roi = cv2.resize(
        roi,
        None,
        fx=2.0,
        fy=2.0,
        interpolation=cv2.INTER_CUBIC
    )

    roi = cv2.copyMakeBorder(
        roi,
        8,
        8,
        8,
        8,
        cv2.BORDER_CONSTANT,
        value=[255, 255, 255]
    )

    ok = cv2.imwrite(image_path, roi)

    if not ok:
        logger.warning(f"保存 ROI 失败: {image_path}")
        return None, None

    label = make_label_from_video_time(time_ms)
    save_label(image_name, label)

    return image_path, label


def collect_all_frames(video_path):
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        return {
            "error": "Failed to open video",
            "saved_count": 0
        }

    saved_count = 0
    skipped_count = 0

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        logger.info(f"开始采集全部帧: {video_path}")
        logger.info(f"FPS: {fps}")
        logger.info(f"总帧数: {total_frames}")

        frame_index = 0

        while True:
            ret, frame = cap.read()

            if not ret:
                break

            time_ms = int((frame_index / fps) * 1000)

            roi = detect_timestamp(frame, frame_index)

            if roi is None or roi.size == 0:
                skipped_count += 1

                if skipped_count % 100 == 0:
                    save_reject_frame(frame, video_path, frame_index)

                frame_index += 1
                continue

            image_path, label = save_roi_image(
                roi=roi,
                video_path=video_path,
                time_ms=time_ms,
                frame_index=frame_index
            )

            if image_path:
                saved_count += 1

            if saved_count % 100 == 0:
                logger.info(
                    f"已保存 {saved_count} 张，当前帧 {frame_index}/{total_frames}，跳过 {skipped_count} 张"
                )

            frame_index += 1

        logger.info(f"采集完成，保存 {saved_count} 张，跳过 {skipped_count} 张")

        return {
            "saved_count": saved_count,
            "skipped_count": skipped_count,
            "total_frames": total_frames,
            "dataset": DATASET_ROOT,
            "image_dir": IMAGE_DIR,
            "reject_dir": REJECT_DIR,
            "mask_dir": MASK_DIR,
            "label_csv": LABEL_CSV
        }

    finally:
        cap.release()


@app.route("/collect_video_all_frames", methods=["GET"])
def collect_video_all_frames_api():
    video_path = request.args.get("path")

    if not video_path:
        return jsonify({"error": "missing path"}), 400

    if not os.path.exists(video_path):
        return jsonify({
            "error": "video path not exists",
            "path": video_path
        }), 400

    result = collect_all_frames(video_path)

    if "error" in result:
        return jsonify(result), 400

    return jsonify(result), 200


@app.route("/dataset_path", methods=["GET"])
def dataset_path_api():
    ensure_label_csv()

    return jsonify({
        "dataset_root": DATASET_ROOT,
        "image_dir": IMAGE_DIR,
        "reject_dir": REJECT_DIR,
        "mask_dir": MASK_DIR,
        "label_csv": LABEL_CSV,
        "image_count": len(os.listdir(IMAGE_DIR)),
        "reject_count": len(os.listdir(REJECT_DIR)),
        "mask_count": len(os.listdir(MASK_DIR)),
        "label_csv_exists": os.path.exists(LABEL_CSV)
    })


if __name__ == "__main__":
    import logging as flask_logging

    flask_logging.getLogger("werkzeug").setLevel(logging.ERROR)

    app.run(
        host="localhost",
        port=5001,
        debug=False
    )
