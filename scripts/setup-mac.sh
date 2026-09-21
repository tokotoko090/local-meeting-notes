#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'Apple Silicon Macが必要です。' >&2; exit 1
fi
python_bin="${PYTHON:-python3.13}"
"$python_bin" -c 'import sys; assert sys.version_info[:2] == (3,13), "Python 3.13が必要です"'
command -v ffmpeg >/dev/null || { echo '先に ffmpeg をインストールしてください。'; exit 1; }
"$python_bin" -m venv .venv-mlx
# Newer macOS hosts would otherwise select macOS 26-only Metal binaries.
# Select the macOS 15 wheels explicitly to preserve the app's minimum OS.
mkdir -p build/mlx-wheels
.venv-mlx/bin/python -m pip download --only-binary=:all: --no-deps \
  --platform macosx_15_0_arm64 --python-version 313 --implementation cp --abi cp313 \
  --dest build/mlx-wheels mlx==0.32.2 mlx-metal==0.32.2
.venv-mlx/bin/python -m pip install --force-reinstall --no-deps \
  build/mlx-wheels/mlx-0.32.2-cp313-cp313-macosx_15_0_arm64.whl \
  build/mlx-wheels/mlx_metal-0.32.2-py3-none-macosx_15_0_arm64.whl
.venv-mlx/bin/python -m pip install -r backend/requirements-macos.lock
.venv-mlx/bin/python -c 'import mlx.core as mx; assert mx.metal.is_available(), "Apple Silicon GPUが利用できません"' 
npm ci
printf '%s\n' 'セットアップ完了。npm run build:mac でアプリを作成します。'
