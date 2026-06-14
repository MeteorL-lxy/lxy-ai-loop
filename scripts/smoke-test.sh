#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$ROOT_DIR/../inbeidou_cli.py" user --json >/dev/null
python3 "$ROOT_DIR/../inbeidou_cli.py" credit --json >/dev/null
python3 "$ROOT_DIR/../inbeidou_cli.py" products --json >/dev/null
python3 "$ROOT_DIR/../inbeidou_cli.py" list --platform dramabox --size 2 --json >/dev/null
python3 "$ROOT_DIR/../inbeidou_cli.py" uploads list --size 2 --json >/dev/null
python3 "$ROOT_DIR/../inbeidou_cli.py" publish accounts --platform FACEBOOK --json >/dev/null

echo "Barry Video smoke test passed."
