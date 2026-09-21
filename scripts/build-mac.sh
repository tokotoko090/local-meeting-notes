#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'Apple Silicon Macでビルドしてください。' >&2; exit 1
fi
# This deliberately honors Xcode's license gate. Agreement is a user action.
xcrun --find swiftc >/dev/null
if [[ ! -x .venv-mlx/bin/python ]]; then
  echo '先に bash scripts/setup-mac.sh を実行してください。' >&2; exit 1
fi
mkdir -p vendor build/mac-module-cache
export PYINSTALLER_CONFIG_DIR="$PWD/build/pyinstaller-cache"
xcrun swiftc -swift-version 5 -parse-as-library -O -target arm64-apple-macos15.0 \
  -module-cache-path "$PWD/build/mac-module-cache" \
  -framework AppKit -framework AVFoundation -framework CoreAudio -framework ScreenCaptureKit \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$PWD/native/macos/Info.plist" \
  native/macos/MeetingAudio.swift -o vendor/MeetingAudio
codesign --force --sign - vendor/MeetingAudio
npm run build
.venv-mlx/bin/python -m PyInstaller --noconfirm --clean --distpath build/mac-backend \
  --workpath build/mac-pyinstaller LocalMeetingNotesMac.spec
node scripts/package-mac.cjs
