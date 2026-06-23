#!/usr/bin/env bash
set -euo pipefail

LOOP_ROOT="${LOOP_ROOT:-/opt/steven-jiao-ai-loop}"
TOOL_DIR="${TOOL_DIR:-$LOOP_ROOT/tools/video-pipeline-tracker}"
API_BASE="${API_BASE:-http://127.0.0.1:8770}"
OWNER="${OWNER:-焦千为}"
UID_VALUE="${UID_VALUE:-2265845568}"
LOOP_NAME="${LOOP_NAME:-steven-jiao-ai-loop}"
REPORT_DATE="${REPORT_DATE:-${1:-$(date +%F)}}"
ROUND_NAME="${ROUND_NAME:-}"
PUBLISH_INTERVAL_SECONDS="${PUBLISH_INTERVAL_SECONDS:-120}"
EXECUTE="${EXECUTE:-0}"
FILTER_WINDOW="${FILTER_WINDOW:-0}"

ENV_FILE="$LOOP_ROOT/.env.server"
DAILY_TARGET="${DAILY_TARGET:-}"
if [[ -z "$DAILY_TARGET" && -f "$ENV_FILE" ]]; then
  DAILY_TARGET="$(grep -E '^STEVEN_LOOP_MIN_SUCCESS_TARGET=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
fi
if [[ -z "$DAILY_TARGET" && -f "$ENV_FILE" ]]; then
  DAILY_TARGET="$(grep -E '^STEVEN_LOOP_COUNT=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
fi
DAILY_TARGET="${DAILY_TARGET:-0}"

PUBLISH_START_TIME="${PUBLISH_START_TIME:-$REPORT_DATE 19:00:00}"
OUT_DIR="${OUT_DIR:-$LOOP_ROOT/runtime/video-pipeline-tracker/$REPORT_DATE}"
TASKS_JSON="$OUT_DIR/tasks-$LOOP_NAME-$REPORT_DATE.json"

mkdir -p "$OUT_DIR"

python3 "$TOOL_DIR/scripts/import_steven_telemetry.py" \
  --loop-root "$LOOP_ROOT" \
  --date "$REPORT_DATE" \
  --api-base "$API_BASE" \
  --assignee "$OWNER" \
  --uid "$UID_VALUE" \
  --loop-name "$LOOP_NAME" \
  --daily-target "$DAILY_TARGET" \
  --publish-start-time "$PUBLISH_START_TIME" \
  --publish-interval-seconds "$PUBLISH_INTERVAL_SECONDS" \
  -o "$TASKS_JSON" >/dev/null

cmd=(
  python3 "$TOOL_DIR/scripts/report_half_hour_loop.py"
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

if [[ -n "$ROUND_NAME" ]]; then
  cmd+=(--round-name "$ROUND_NAME")
fi
if [[ "$FILTER_WINDOW" == "1" ]]; then
  cmd+=(--filter-window)
fi
if [[ "$EXECUTE" == "1" ]]; then
  cmd+=(--execute)
fi

"${cmd[@]}"
