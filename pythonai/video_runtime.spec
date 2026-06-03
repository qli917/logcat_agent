# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules
import importlib.util


block_cipher = None

excluded_modules = [
    "torch",
    "torchvision",
    "torchaudio",
    "nvidia",
    "triton",
    "tensorboard",
    "tensorflow",
    "scipy",
    "sklearn",
    "matplotlib",
    "pandas",
    "PIL.ImageTk",
    "modelscope",
    "paddle",
    "onnx",
    "onnxruntime.tools",
    "onnxruntime.quantization",
    "onnxruntime.transformers",
    "skimage",
    "shapely",
    "av",
    "tokenizers",
    "huggingface_hub",
    "transformers",
    "soundfile",
    "librosa",
    "numba",
    "llvmlite",
]


def package_dir(package_name):
    spec = importlib.util.find_spec(package_name)
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError(f"Cannot find package: {package_name}")
    return next(iter(spec.submodule_search_locations))

a = Analysis(
    ["video.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("timestamp_crnn_best.onnx", "."),
        ("funasr-paraformer-zh", "funasr-paraformer-zh"),
        (package_dir("funasr_onnx"), "funasr_onnx"),
    ],
    hiddenimports=[
        "onnxruntime",
        "onnxruntime.capi.onnxruntime_pybind11_state",
        "kaldi_native_fbank",
        "yaml",
        "jieba",
        "sentencepiece",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="logagent-python",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="logagent-python",
)
