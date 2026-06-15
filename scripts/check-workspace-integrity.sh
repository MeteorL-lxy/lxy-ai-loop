#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${BARRY_WORKSPACE_GUARD_STATE_DIR:-$ROOT_DIR/runtime/workspace-guard}"
mkdir -p "$STATE_DIR"

timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
snapshot_file="$STATE_DIR/latest.json"
log_file="$STATE_DIR/integrity.log"

source_file_count="$(find "$ROOT_DIR" \
  -path "$ROOT_DIR/.git" -prune -o \
  -path "$ROOT_DIR/data" -prune -o \
  -path "$ROOT_DIR/runtime" -prune -o \
  -path "$ROOT_DIR/logs" -prune -o \
  -type f -print | wc -l | tr -d ' ')"

missing=()
for required_path in backend scripts conf skills openclaw.plugin.json; do
  if [ ! -e "$ROOT_DIR/$required_path" ]; then
    missing+=("$required_path")
  fi
done

status="ok"
if [ "${source_file_count:-0}" -lt 60 ] || [ "${#missing[@]}" -gt 0 ]; then
  status="failed"
fi

python3 - "$snapshot_file" "$timestamp" "$ROOT_DIR" "$source_file_count" "$status" "${missing[@]+"${missing[@]}"}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "checked_at": sys.argv[2],
    "root_dir": sys.argv[3],
    "source_file_count": int(sys.argv[4] or 0),
    "status": sys.argv[5],
    "missing_required_paths": sys.argv[6:],
}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

printf '%s status=%s source_file_count=%s missing=%s\n' "$timestamp" "$status" "$source_file_count" "${missing[*]:-}" >>"$log_file"

if [ "$status" != "ok" ]; then
  echo "Workspace integrity check failed. See $snapshot_file" >&2
  exit 1
fi

echo "Workspace integrity ok: $source_file_count source files."
