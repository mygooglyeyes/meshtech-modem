#!/bin/bash
# meshtech-modem launcher - the only thing systemd (or you) runs.
# Handles the virtualenv so nobody has to know it exists.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/pip install --quiet -r requirements.txt || true
fi
exec .venv/bin/python modem.py
