#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Virtual environment .venv not found."
  exit 1
fi

source .venv/bin/activate

pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "Substack Studio" \
  --add-data "assets:assets" \
  --add-data "author_template.html:." \
  --add-data "config.py:." \
  substack_gui.py

echo "Built app bundle at: $ROOT_DIR/dist/Substack Studio.app"
