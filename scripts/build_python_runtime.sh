#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_DIR="$ROOT_DIR/pythonai"
VENV_DIR="$ROOT_DIR/.venv-runtime"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel
"$VENV_DIR/bin/python" -m pip install -r "$PY_DIR/requirements-runtime.txt" pyinstaller

if "$VENV_DIR/bin/python" - <<'PY'
import importlib.util
import sys

blocked = ["torch", "torchvision", "torchaudio", "nvidia", "triton"]
found = [name for name in blocked if importlib.util.find_spec(name)]
if found:
    print("Blocked runtime dependencies installed:", ", ".join(found))
    sys.exit(1)
PY
then
    :
else
    echo "Runtime venv must not contain PyTorch/CUDA packages." >&2
    exit 1
fi

cd "$PY_DIR"
"$VENV_DIR/bin/pyinstaller" --clean --noconfirm video_runtime.spec

echo "Built Python runtime: $PY_DIR/dist/logagent-python"
