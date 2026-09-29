@echo off
setlocal
cd /d "%~dp0"

echo Сборка AdFox Logs для Windows...
if not exist ".venv-build\Scripts\python.exe" py -3 -m venv .venv-build
if errorlevel 1 goto :failed

".venv-build\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto :failed
".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --clean adfox_logs.spec
if errorlevel 1 goto :failed

echo Готово: dist\AdFox Logs.exe
exit /b 0

:failed
echo Сборка не завершена. Проверьте сообщение выше.
pause
exit /b 1
