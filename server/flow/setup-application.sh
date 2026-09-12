#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET_DIR="$SCRIPT_DIR/custom_libs"
WHEEL_DIR="$SCRIPT_DIR/whl"

python -c "import sys; assert sys.version_info[:2] == (3, 11), sys.version"
python -c "import dlp, fastapi, gunicorn, uvicorn"
python "$SCRIPT_DIR/verify_wheels.py" "$WHEEL_DIR"
mkdir -p "$TARGET_DIR"
python -m pip install \
  --no-index \
  --disable-pip-version-check \
  --no-deps \
  --target "$TARGET_DIR" \
  --find-links "$WHEEL_DIR" \
  -r "$SCRIPT_DIR/requirements.txt"
