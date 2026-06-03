#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 0 ]]; then
    export LOGCAT_AGENT_MODEL_BUNDLE_URL="$1"
fi

if [[ -z "${LOGCAT_AGENT_MODEL_BUNDLE_URL:-}" ]]; then
    echo "Usage: $0 https://example.com/logagent-models.zip" >&2
    echo "Or set LOGCAT_AGENT_MODEL_BUNDLE_URL before running." >&2
    exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 - <<'PY'
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "pythonai"))

import model_download

model_download.ensure_model_bundle()

print("Model directory:", model_download.MODEL_DATA_DIR)
print("OCR ONNX:", model_download.DOWNLOADED_ONNX_MODEL_PATH)
print("FunASR:", model_download.DOWNLOADED_FUNASR_MODEL_PATH)
PY
