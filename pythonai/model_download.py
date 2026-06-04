import os
import shutil
import tarfile
import tempfile
import zipfile

import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
MODEL_DATA_DIR = os.environ.get(
    "LOGCAT_AGENT_MODEL_DIR",
    os.path.join(PROJECT_ROOT, "logagent_models"),
)

DOWNLOADED_ONNX_MODEL_PATH = os.path.join(MODEL_DATA_DIR, "timestamp_crnn_best.onnx")
DOWNLOADED_FUNASR_MODEL_PATH = os.path.join(MODEL_DATA_DIR, "funasr-paraformer-zh")
MODEL_BUNDLE_READY_PATH = os.path.join(MODEL_DATA_DIR, ".bundle_ready")


def download_file(url, target_path):
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    temp_path = target_path + ".download"

    if url.startswith("file://"):
        source_path = url[len("file://"):]
        shutil.copy2(source_path, temp_path)
        os.replace(temp_path, target_path)
        return

    with requests.get(url, stream=True, timeout=(10, 60)) as response:
        response.raise_for_status()
        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    os.replace(temp_path, target_path)


def has_funasr_model_files(model_dir):
    if not os.path.isdir(model_dir):
        return False

    has_onnx = False
    has_config = False

    for _, _, files in os.walk(model_dir):
        for name in files:
            lower = name.lower()
            has_onnx = has_onnx or lower.endswith(".onnx")
            has_config = has_config or lower in {
                "config.yaml",
                "config.yml",
                "config.json",
                "configuration.json",
            }

    return has_onnx and has_config


def copy_tree_contents(source_dir, target_dir):
    os.makedirs(target_dir, exist_ok=True)

    for name in os.listdir(source_dir):
        source_path = os.path.join(source_dir, name)
        target_path = os.path.join(target_dir, name)

        if os.path.isdir(source_path):
            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
            shutil.copytree(source_path, target_path)
        else:
            shutil.copy2(source_path, target_path)


def find_model_bundle_root(extract_dir):
    required_names = {
        "timestamp_crnn_best.onnx",
        "funasr-paraformer-zh",
    }

    for current_root, dirs, files in os.walk(extract_dir):
        names = set(dirs) | set(files)
        if required_names.intersection(names):
            return current_root

    return extract_dir


def model_bundle_is_ready():
    return (
        os.path.exists(DOWNLOADED_ONNX_MODEL_PATH)
        and has_funasr_model_files(DOWNLOADED_FUNASR_MODEL_PATH)
    )


def ensure_model_bundle():
    os.makedirs(MODEL_DATA_DIR, exist_ok=True)

    if os.path.exists(MODEL_BUNDLE_READY_PATH) and model_bundle_is_ready():
        return

    if model_bundle_is_ready():
        with open(MODEL_BUNDLE_READY_PATH, "w", encoding="utf-8") as f:
            f.write("ready\n")
        return

    url = os.environ.get("LOGCAT_AGENT_MODEL_BUNDLE_URL", "").strip()
    if not url:
        return

    archive_name = os.path.basename(url.split("?", 1)[0]) or "logagent-models.zip"
    archive_path = os.path.join(MODEL_DATA_DIR, archive_name)

    download_file(url, archive_path)

    with tempfile.TemporaryDirectory(prefix="logagent_model_bundle_") as temp_dir:
        if zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(temp_dir)
        elif tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path) as archive:
                archive.extractall(temp_dir)
        else:
            raise ValueError("模型包必须是 zip、tar 或 tar.gz 格式")

        bundle_root = find_model_bundle_root(temp_dir)
        copy_tree_contents(bundle_root, MODEL_DATA_DIR)

    try:
        os.remove(archive_path)
    except OSError:
        pass

    with open(MODEL_BUNDLE_READY_PATH, "w", encoding="utf-8") as f:
        f.write("ready\n")
