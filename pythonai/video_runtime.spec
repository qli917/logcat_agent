# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


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
]

a = Analysis(
    ["video.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        *collect_submodules("funasr_onnx"),
        *collect_submodules("onnxruntime"),
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
