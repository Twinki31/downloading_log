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

py -3 launcher_env.py check-python
if errorlevel 1 (
    echo Install Python 3.11 or newer, then run this file again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the project environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" launcher_env.py check-python
if errorlevel 1 (
    echo The existing .venv uses an old Python. Delete .venv and run this file again.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" launcher_env.py sync requirements.txt ".venv\requirements.sha256"
if errorlevel 1 (
    echo The app could not start because its libraries could not be installed.
    goto :failed
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
