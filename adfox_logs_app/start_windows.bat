@echo off
setlocal
cd /d "%~dp0"

echo Starting AdFox logs...
where py >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Install Python 3.11 or newer, then run this file again.
    echo If you use the Python install manager, run: py install 3.14
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the project environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info < (3, 11))"
if errorlevel 1 (
    echo Python 3.11 or newer is required. Install it, then run this file again.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "import streamlit, boto3" >nul 2>&1
if errorlevel 1 (
    echo Installing the required libraries. This needs an internet connection...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :failed
)

echo Starting the app. Keep this window open while using it.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.maxUploadSize 1
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo The app could not start. Check the error above.
pause
exit /b 1
