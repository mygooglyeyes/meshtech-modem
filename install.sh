#!/bin/bash
# meshtech-modem service installer for Linux.
#
# One-time setup:
#   ./install.sh
#
# Afterwards the modem runs as a systemd service (starts on boot,
# restarts if it crashes). Everyday commands:
#   systemctl status  meshtech-modem    - is it running?
#   journalctl -u meshtech-modem -f     - live log
#   sudo systemctl restart meshtech-modem  - after editing modem.conf
#
# Everyday workflow after code changes:
#   git pull && sudo systemctl restart meshtech-modem

set -euo pipefail
cd "$(dirname "$0")"

# venv is managed here so the user never touches it.
if [ ! -x .venv/bin/python ]; then
    echo "Creating virtualenv..."
    python3 -m venv .venv
fi
# Runtime dependencies (PyNaCl, for the signed demo feed).
.venv/bin/pip install --quiet -r requirements.txt

# Local settings file (never committed).
if [ ! -f modem.conf ]; then
    cp modem.conf.example modem.conf
    echo "Created modem.conf from the example."
fi

# Feed password: without it the feed port stays closed.
if [ ! -f .feed_token ]; then
    echo
    echo "No feed password found (.feed_token missing)."
    echo "Set one now so the bot can push packets (recommended),"
    echo "or skip and run ./set-feed-token.sh later."
    if [[ -t 0 ]]; then
        read -r -p "Set the feed password now? [Y/n] " yn
        if [[ ! "$yn" =~ ^[Nn] ]]; then
            ./set-feed-token.sh && exit 0
        fi
        echo "Skipping - remember: no password file = feed port closed."
    else
        echo "Non-interactive install - run ./set-feed-token.sh afterwards."
    fi
fi

# systemd unit runs run.sh, which handles the venv transparently.
sudo tee /etc/systemd/system/meshtech-modem.service > /dev/null <<EOF
[Unit]
Description=meshtech-modem - openHop pymc_tcp modem emulator
After=network.target

[Service]
Type=simple
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/run.sh
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now meshtech-modem
echo
echo "Installed and started. Check it:"
echo "  systemctl status meshtech-modem"
echo "  journalctl -u meshtech-modem -f"
