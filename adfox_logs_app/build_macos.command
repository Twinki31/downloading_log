#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "Сборка AdFox Logs для macOS..."
if [ ! -x ".venv-build/bin/python" ]; then
    python3 -m venv ".venv-build"
fi

".venv-build/bin/python" -m pip install -r requirements-build.txt
".venv-build/bin/python" -m PyInstaller --noconfirm --clean adfox_logs.spec
./create_dmg.sh

echo "Готово: dist/AdFox-Logs-macOS.dmg"
