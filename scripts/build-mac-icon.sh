#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'Macのアイコン生成にはmacOSとXcode 26以降が必要です。' >&2
  exit 1
fi
xcrun --find actool >/dev/null
icon_source="$PWD/native/macos/AppIcon.icon"
icon_output="$PWD/build/mac-icon"
[[ -f "$icon_source/icon.json" ]] || { echo "Icon Composerファイルが見つかりません: $icon_source" >&2; exit 1; }
mkdir -p "$icon_output"
xcrun actool "$icon_source" \
  --compile "$icon_output" \
  --output-format human-readable-text --notices --warnings \
  --output-partial-info-plist "$icon_output/partial-info.plist" \
  --app-icon AppIcon --include-all-app-icons --target-device mac \
  --minimum-deployment-target 15.0 --platform macosx \
  --standalone-icon-behavior all
[[ -s "$icon_output/Assets.car" && -s "$icon_output/AppIcon.icns" ]] || {
  echo 'レイヤーアイコンまたは旧OS用アイコンが生成されませんでした。' >&2
  exit 1
}
