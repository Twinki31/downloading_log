@echo off
setlocal
cd /d "%~dp0"

echo Сборка AdFox Logs для Windows...
if not exist ".venv-build\Scripts\python.exe" python -m venv .venv-build
if not exist ".venv-build\Scripts\python.exe" py -3 -m venv .venv-build
if errorlevel 1 goto :failed

".venv-build\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto :failed
".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --clean adfox_logs.spec
if errorlevel 1 goto :failed

set "APP_VERSION="
set /p "APP_VERSION="<VERSION
if not defined APP_VERSION goto :failed

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Не найден Inno Setup 6. Установите его и повторите сборку.
    goto :failed
)
"%ISCC%" /DMyAppVersion=%APP_VERSION% windows_installer.iss
if errorlevel 1 goto :failed

echo Готово: dist\AdFox-Logs-Windows-Setup.exe
exit /b 0

:failed
echo Сборка не завершена. Проверьте сообщение выше.
if not defined CI pause
exit /b 1
