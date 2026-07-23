#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    if ! command -v python3.11 >/dev/null 2>&1; then
        echo "Python 3.11 is required and was not found." >&2
        exit 1
    fi
    echo "Creating Python 3.11 virtual environment..."
    python3.11 -m venv .venv
fi

echo "Checking project dependencies..."
"$VENV_PYTHON" -m pip install --disable-pip-version-check -r requirements.txt
exec "$VENV_PYTHON" gradio_tts_nano_app.py
