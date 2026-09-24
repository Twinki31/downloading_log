#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import streamlit, boto3' >/dev/null 2>&1; then
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.maxUploadSize 1
