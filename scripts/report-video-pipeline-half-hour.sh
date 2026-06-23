#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${LOOP_ROOT:-/Users/xinyuliu/Desktop/work/barry-video}"
cd "$ROOT_DIR"

REPORT_DATE="${1:-$(date +%F)}"
TRACKER_DIR="$ROOT_DIR/tools/video-pipeline-tracker"
CONFIG_FILE="$ROOT_DIR/conf/video_pipeline_tracker.json"
OUT_DIR="$ROOT_DIR/runtime/video-pipeline-tracker/$REPORT_DATE"
TASKS_JSON="$OUT_DIR/tasks-liuxinyu-ai-loop-$REPORT_DATE.json"

read_config() {
  local key="$1"
  local default_value="${2:-}"
  python3 - "$CONFIG_FILE" "$key" "$default_value" <<'PY'
import json
import sys
from pathlib import Path

path, key, default = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
except Exception:
    data = {}
value = data.get(key, default)
print("" if value is None else value)
PY
}

API_BASE="${API_BASE:-$(read_config api_base http://124.174.76.6)}"
OWNER="${OWNER:-$(read_config owner 刘心雨)}"
UID_VALUE="${UID_VALUE:-$(read_config uid 9402541668)}"
LOOP_NAME="${LOOP_NAME:-$(read_config loop_name liuxinyu-ai-loop)}"
PUBLISH_INTERVAL_SECONDS="${PUBLISH_INTERVAL_SECONDS:-$(read_config publish_interval_seconds 120)}"
EXECUTE="${EXECUTE:-0}"
FILTER_WINDOW="${FILTER_WINDOW:-0}"
STRICT="${STRICT:-0}"

mkdir -p "$OUT_DIR"

python3 - "$REPORT_DATE" "$TASKS_JSON" <<'PY'
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

report_date, output = sys.argv[1], Path(sys.argv[2])
root = Path("runtime/continuous-loop") / report_date
rows = []
sources = []

def load_rows(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], f"{path}: {exc}"
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        return [row for row in data["rows"] if isinstance(row, dict)], ""
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)], ""
    if isinstance(data, dict):
        # Empty tracker files are useful as diagnostics but should not poison the snapshot.
        if data.get("stage") or data.get("error") or data.get("ok") is False:
            return [], ""
        return [data], ""
    return [], f"{path}: unsupported json shape"

for path in sorted(root.glob("*/*/tasks.json")):
    loaded, warning = load_rows(path)
    if warning:
        sources.append({"file": str(path), "warning": warning, "rows": 0})
        continue
    if loaded:
        for index, row in enumerate(loaded, start=1):
            copied = dict(row)
            copied["_tracker_source_file"] = str(path)
            copied["_tracker_source_index"] = index
            rows.append(copied)
        sources.append({"file": str(path), "rows": len(loaded)})

task_id_counts = Counter(str(row.get("task_id") or "").strip() for row in rows)
for row in rows:
    original_task_id = str(row.get("task_id") or "").strip()
    if not original_task_id or task_id_counts[original_task_id] > 1:
        seed = json.dumps(
            {
                "original_task_id": original_task_id,
                "source_file": row.get("_tracker_source_file"),
                "source_index": row.get("_tracker_source_index"),
                "account": row.get("social_account_id") or row.get("channel_id") or row.get("publish_account_id"),
                "round": row.get("round_name"),
                "drama": row.get("drama_name"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        row["tracker_original_task_id"] = original_task_id
        row["task_id"] = f"loop_result:{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:20]}"
    row.pop("_tracker_source_file", None)
    row.pop("_tracker_source_index", None)

output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    json.dumps({"rows": rows, "sources": sources}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(json.dumps({"output": str(output), "rows": len(rows), "source_files": len(sources)}, ensure_ascii=False))
PY

cmd=(
  python3 "$TRACKER_DIR/scripts/report_half_hour_loop.py"
  --tasks "$TASKS_JSON"
  --api-base "$API_BASE"
  --owner "$OWNER"
  --uid "$UID_VALUE"
  --loop-name "$LOOP_NAME"
  --publish-interval-seconds "$PUBLISH_INTERVAL_SECONDS"
  --output-dir "$OUT_DIR/half-hour-reports"
)

if [[ "${DAILY_TARGET:-}" != "" ]]; then
  cmd+=(--daily-target "$DAILY_TARGET")
fi

if [[ "${PUBLISH_START_TIME:-}" != "" ]]; then
  cmd+=(--publish-start-time "$PUBLISH_START_TIME")
fi

if [[ "$FILTER_WINDOW" == "1" ]]; then
  cmd+=(--filter-window)
fi

if [[ "$STRICT" == "1" ]]; then
  cmd+=(--strict)
fi

if [[ "$EXECUTE" == "1" ]]; then
  cmd+=(--execute)
fi

"${cmd[@]}"
