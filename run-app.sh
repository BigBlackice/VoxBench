#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
VENV_PYTHON="$SCRIPT_DIR/.venv-app/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    command -v python3.11 >/dev/null 2>&1 || {
        echo "Python 3.11 is required and was not found." >&2
        exit 1
    }
    python3.11 -m venv .venv-app
fi

"$VENV_PYTHON" -m pip install --disable-pip-version-check -r requirements-app.txt
exec "$VENV_PYTHON" app.py
