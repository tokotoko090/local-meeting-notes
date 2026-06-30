# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


datas = [
    ("dist", "dist"),
]

if Path("vendor").exists():
    datas.append(("vendor", "vendor"))

for package_name in ("faster_whisper", "tokenizers", "huggingface_hub"):
    datas += collect_data_files(package_name)

datas += collect_dynamic_libs("ctranslate2")

hiddenimports = [
    "av",
    "ctranslate2",
    "faster_whisper",
    "faster_whisper.audio",
    "faster_whisper.transcribe",
    "huggingface_hub",
    "pyaudiowpatch",
    "tokenizers",
]

excludes = [
    "fairseq",
    "librosa",
    "numba",
    "opennmt",
    "onnxruntime",
    "pandas",
    "pytest",
    "scipy",
    "sklearn",
    "tensorflow",
    "torch",
    "transformers",
]


a = Analysis(
    ["app_launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LocalMeetingNotes",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
