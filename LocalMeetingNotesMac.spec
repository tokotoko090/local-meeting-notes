# Build on Apple Silicon using the same Python environment as runtime tests.
from pathlib import Path
import shutil
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

ffmpeg = shutil.which('ffmpeg')
if not ffmpeg:
    raise RuntimeError('ffmpeg is required to build the self-contained Mac app')
datas = []
binaries = [(ffmpeg, 'vendor')]
for package in ('mlx', 'mlx_whisper', 'tiktoken', 'huggingface_hub', 'certifi'):
    datas += collect_data_files(package)
for package in ('mlx', 'llvmlite'):
    binaries += collect_dynamic_libs(package)
# Keep package discovery metadata and tokenizer plugins available offline.
for package in ('mlx', 'mlx-whisper', 'huggingface_hub', 'tiktoken'):
    datas += copy_metadata(package)
# mlx.core imports these Python helpers from C++, invisible to static analysis.
hiddenimports = ['backend.macos', 'av', 'mlx.core', 'mlx._reprlib_fix', 'mlx.__array_api_info', 'mlx_whisper', 'hf_xet']
hiddenimports += collect_submodules('tiktoken_ext')
a = Analysis(['app_launcher.py'], pathex=[str(Path.cwd())], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports,
             excludes=['pyaudiowpatch', 'faster_whisper', 'ctranslate2', 'onnxruntime', 'mlx_whisper.torch_whisper', 'torch', 'tensorflow', 'pandas', 'pytest', 'tkinter'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LocalMeetingNotesBackend',
          console=True, target_arch='arm64', codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='LocalMeetingNotesBackend')
