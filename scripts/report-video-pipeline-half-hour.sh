#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${LOOP_ROOT:-/Users/xinyuliu/Desktop/work/barry-video}"
cd "$ROOT_DIR"

REPORT_DATE="${REPORT_DATE:-${1:-$(date +%F)}}"
TRACKER_DIR="$ROOT_DIR/tools/video-pipeline-tracker"
CONFIG_FILE="$ROOT_DIR/conf/video_pipeline_tracker.json"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/runtime/video-pipeline-tracker/$REPORT_DATE}"
TASKS_JSON="$OUT_DIR/tasks-liuxinyu-ai-loop-$REPORT_DATE.json"
META_JSON="$OUT_DIR/tasks-liuxinyu-ai-loop-$REPORT_DATE.meta.json"

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
DAILY_TARGET="${DAILY_TARGET:-$(read_config daily_target "")}"
PUBLISH_START_TIME="${PUBLISH_START_TIME:-$(read_config publish_start_time "")}"
PUBLISHED_TODAY="${PUBLISHED_TODAY:-$(read_config published_today "")}"
ROUND_NAME="${ROUND_NAME:-$(read_config round_name "")}"
VERIFY_LIMIT="${VERIFY_LIMIT:-$(read_config verify_limit 100000)}"
SKIP_INGEST_VERIFY="${SKIP_INGEST_VERIFY:-0}"
ALLOW_OWNER_MISMATCH="${ALLOW_OWNER_MISMATCH:-0}"
EXECUTE="${EXECUTE:-0}"
FILTER_WINDOW="${FILTER_WINDOW:-0}"
STRICT="${STRICT:-0}"

mkdir -p "$OUT_DIR"

python3 - "$REPORT_DATE" "$TASKS_JSON" "$META_JSON" <<'PY'
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

report_date, output, meta_output = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
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

def parse_dt(value):
    raw = str(value or "").strip().replace("T", " ")[:19]
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None

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
times = []
for row in rows:
    for field in ("update_time", "drama_timestamp", "short_link_publish_time", "publish_req_start_time", "date"):
        parsed = parse_dt(row.get(field))
        if parsed:
            times.append(parsed)
            break
meta = {
    "output": str(output),
    "rows": len(rows),
    "source_files": len(sources),
    "inferred_daily_target": len(rows),
    "inferred_publish_start_time": min(times).strftime("%Y-%m-%d %H:%M:%S") if times else f"{report_date} 00:00:00",
}
meta_output.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False))
PY

if [[ -z "$DAILY_TARGET" ]]; then
  DAILY_TARGET="$(python3 - "$META_JSON" <<'PY'
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(data.get("inferred_daily_target") or "")
PY
)"
fi

if [[ -z "$PUBLISH_START_TIME" ]]; then
  PUBLISH_START_TIME="$(python3 - "$META_JSON" <<'PY'
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(data.get("inferred_publish_start_time") or "")
PY
)"
fi

python3 - "$TASKS_JSON" "$PUBLISH_START_TIME" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
publish_start_time = str(sys.argv[2] or "").strip()
if not publish_start_time:
    raise SystemExit(0)
data = json.loads(path.read_text(encoding="utf-8"))
rows = data.get("rows") if isinstance(data, dict) else []
if not isinstance(rows, list):
    raise SystemExit(0)
changed = False
for row in rows:
    if not isinstance(row, dict):
        continue
    status = str(row.get("publish_status") or "").strip().lower()
    if not str(row.get("publish_schedule_start_time") or "").strip():
        row["publish_schedule_start_time"] = publish_start_time
        changed = True
    if not str(row.get("publish_start_time") or "").strip():
        row["publish_start_time"] = publish_start_time
        changed = True
    if status not in {"failed", "cancelled", "error"} and not str(row.get("short_link_publish_time") or "").strip():
        row["short_link_publish_time"] = publish_start_time
        changed = True
if changed:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
PY

cmd=(
  python3 "$TRACKER_DIR/scripts/report_half_hour_loop.py"
  --tasks "$TASKS_JSON"
  --api-base "$API_BASE"
  --owner "$OWNER"
  --uid "$UID_VALUE"
  --loop-name "$LOOP_NAME"
  --daily-target "$DAILY_TARGET"
  --publish-start-time "$PUBLISH_START_TIME"
  --publish-interval-seconds "$PUBLISH_INTERVAL_SECONDS"
  --output-dir "$OUT_DIR/half-hour-reports"
)

if [[ -n "$PUBLISHED_TODAY" ]]; then
  cmd+=(--published-today "$PUBLISHED_TODAY")
fi

if [[ -n "$ROUND_NAME" ]]; then
  cmd+=(--round-name "$ROUND_NAME")
fi

if [[ -n "$VERIFY_LIMIT" ]]; then
  cmd+=(--verify-limit "$VERIFY_LIMIT")
fi

if [[ "$FILTER_WINDOW" == "1" ]]; then
  cmd+=(--filter-window)
fi

if [[ "$STRICT" == "1" ]]; then
  cmd+=(--strict)
fi

if [[ "$ALLOW_OWNER_MISMATCH" == "1" ]]; then
  cmd+=(--allow-owner-mismatch)
fi

if [[ "$SKIP_INGEST_VERIFY" == "1" ]]; then
  cmd+=(--skip-ingest-verify)
fi

if [[ "$EXECUTE" == "1" ]]; then
  cmd+=(--execute)
fi

"${cmd[@]}"
