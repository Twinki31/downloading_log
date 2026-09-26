#!/bin/bash
cd "$(dirname "$0")" || exit 1

echo "Starting AdFox logs..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python was not found. Install Python 3.11 or newer, then run this file again."
    exit 1
fi

if ! python3 launcher_env.py check-python; then
    echo "Install Python 3.11 or newer, then run this file again."
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Creating the project environment..."
    if ! python3 -m venv ".venv"; then
        echo "The project environment could not be created. Check the error above."
        exit 1
    fi
fi

if ! ".venv/bin/python" launcher_env.py check-python; then
    echo "The existing .venv uses an old Python. Delete .venv and run this file again."
    exit 1
fi

if ! ".venv/bin/python" launcher_env.py sync requirements.txt ".venv/requirements.sha256"; then
    echo "The app could not start because its libraries could not be installed."
    exit 1
fi

echo "Starting the app. Keep this window open while using it."
exec ".venv/bin/python" -m streamlit run app.py --server.address 127.0.0.1 --server.maxUploadSize 1
