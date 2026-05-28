import os
import csv
import re
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_DIR = os.path.join(BASE_DIR, "debug_ocr", "roi_dataset", "images")
LABEL_CSV = os.path.join(BASE_DIR, "debug_ocr", "roi_dataset", "labels.csv")

BASE_TIMESTAMP = datetime.strptime(
    "2026-05-07 16:46:33.988",
    "%Y-%m-%d %H:%M:%S.%f"
)

files = sorted(os.listdir(IMAGE_DIR))

with open(LABEL_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["image", "label"])

    for file in files:
        if not file.endswith(".png"):
            continue

        match = re.search(r"_(\d+)ms\.png$", file)
        if not match:
            continue

        time_ms = int(match.group(1))
        label_time = BASE_TIMESTAMP + timedelta(milliseconds=time_ms)
        label = label_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        writer.writerow([file, label])

print("labels.csv 已修正")