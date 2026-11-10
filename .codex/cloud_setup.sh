#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Configure the Codex environment for Python 3.11 before running this script.
PYTHON_BIN="${MARKETLENS_PYTHON:-python3}"
"$PYTHON_BIN" -c 'import sys; assert (3,11) <= sys.version_info[:2] <= (3,12), "Use Python 3.11 or 3.12 for pinned PySide6"'
if command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" = 0 ]; then
  apt-get update -qq
  apt-get install -y --no-install-recommends libegl1 libopengl0 libgl1 libxkbcommon0 fontconfig fonts-dejavu-core
fi
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -c 'import PySide6.QtWidgets, sqlalchemy, pydantic, jwt, filelock; print("MarketLens cloud dependencies imported")'
printf '%s\n' 'Setup complete. Use .venv/bin/python; read CLOUD_HANDOFF.md for checks and platform limits.'
