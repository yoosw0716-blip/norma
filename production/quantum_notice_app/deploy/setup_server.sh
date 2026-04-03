#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/quantum_notice_app
PYTHON_BIN=python3

sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER":"$USER" "$APP_DIR"

cd "$APP_DIR"

if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

mkdir -p data

echo "Setup complete: $APP_DIR"
