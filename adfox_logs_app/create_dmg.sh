#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

app_path="dist/AdFox Logs.app"
dmg_path="dist/AdFox-Logs-macOS.dmg"
stage_path="build/dmg"

if [ ! -d "$app_path" ]; then
    echo "Не найдено приложение: $app_path" >&2
    exit 1
fi

rm -rf "$stage_path"
mkdir -p "$stage_path"
cp -R "$app_path" "$stage_path/AdFox Logs.app"
ln -s /Applications "$stage_path/Applications"
rm -f "$dmg_path"

hdiutil create \
    -volname "AdFox Logs" \
    -srcfolder "$stage_path" \
    -format UDZO \
    -ov \
    "$dmg_path"

echo "Готово: $dmg_path"
