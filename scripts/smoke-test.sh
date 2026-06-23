#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLI="$ROOT_DIR/backend/inbeidou_cli.py"

python3 "$CLI" user --json >/dev/null
python3 "$CLI" credit --json >/dev/null
python3 "$CLI" products --json >/dev/null
python3 "$CLI" list --platform dramabox --size 2 --json >/dev/null
python3 "$CLI" uploads list --size 2 --json >/dev/null
python3 "$CLI" publish accounts --platform FACEBOOK --json >/dev/null

echo "Barry Video smoke test passed."
