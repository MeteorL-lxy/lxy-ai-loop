#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PLATFORM="${BARRY_NOVEL_LOOP_PLATFORM:-FACEBOOK}"
COUNT="${BARRY_NOVEL_LOOP_COUNT:-20}"
ACCOUNT_POOL="${BARRY_NOVEL_LOOP_ACCOUNT_POOL:-facebook_novel_dedicated_10}"
START_AT="${BARRY_NOVEL_LOOP_START_AT:-11:00}"
END_AT="${BARRY_NOVEL_LOOP_END_AT:-09:00}"
INTERVAL_SECONDS="${BARRY_NOVEL_LOOP_INTERVAL_SECONDS:-600}"
STATE_ROOT="${BARRY_NOVEL_LOOP_STATE_ROOT:-$ROOT_DIR/runtime/novel-loop}"
REPORT_DIR="${BARRY_NOVEL_LOOP_REPORT_DIR:-$ROOT_DIR/runtime/reports/novel-loop}"
DELETE_LOCAL_OUTPUT="${BARRY_NOVEL_DELETE_LOCAL_OUTPUT_AFTER_PUBLISH:-1}"
PID_FILE="$STATE_ROOT/scheduler.pid"
TODAY="$(date +%F)"
RUN_DIR="$STATE_ROOT/$TODAY"
LOG_FILE="$RUN_DIR/scheduler.log"

mkdir -p "$RUN_DIR" "$REPORT_DIR"
touch "$LOG_FILE"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG_FILE"
}

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    log "小说 loop 调度器已在运行，pid=${EXISTING_PID}，跳过重复启动。"
    exit 0
  fi
fi

echo "$$" > "$PID_FILE"
cleanup() {
  rm -f "$PID_FILE"
}
trap cleanup EXIT

timestamp_for_day() {
  python3 - "$1" "$2" <<'PY'
from datetime import datetime
import sys

day = sys.argv[1].strip()
hhmm = sys.argv[2].strip()
hour, minute = map(int, hhmm.split(":"))
dt = datetime.strptime(day, "%Y-%m-%d").replace(hour=hour, minute=minute, second=0, microsecond=0)
print(int(dt.timestamp()))
PY
}

add_days() {
  python3 - "$1" "$2" <<'PY'
from datetime import datetime, timedelta
import sys

day = datetime.strptime(sys.argv[1], "%Y-%m-%d")
offset = int(sys.argv[2])
print((day + timedelta(days=offset)).strftime("%F"))
PY
}

START_DAY="$(date +%F)"
END_DAY="$START_DAY"
START_EPOCH="$(timestamp_for_day "$START_DAY" "$START_AT")"
END_EPOCH="$(timestamp_for_day "$END_DAY" "$END_AT")"
if (( END_EPOCH <= START_EPOCH )); then
  END_DAY="$(add_days "$START_DAY" 1)"
  END_EPOCH="$(timestamp_for_day "$END_DAY" "$END_AT")"
fi

NOW_EPOCH="$(date +%s)"
if (( NOW_EPOCH < START_EPOCH )); then
  WAIT_SECONDS=$((START_EPOCH - NOW_EPOCH))
  log "等待小说 loop 启动：开始时间 ${START_DAY} ${START_AT}，剩余 ${WAIT_SECONDS} 秒。"
  sleep "$WAIT_SECONDS"
fi

ROUND_INDEX=0
LAST_ROUND="$(
  RUN_DIR="$RUN_DIR" python3 - <<'PY'
from pathlib import Path
import os
import re

run_dir = Path(os.environ["RUN_DIR"])
max_round = 0
pattern = re.compile(r"^round_(\d+)\.json$")
for path in run_dir.glob("round_*.json"):
    match = pattern.match(path.name)
    if match:
        max_round = max(max_round, int(match.group(1)))
print(max_round)
PY
)"
if [[ -n "$LAST_ROUND" ]]; then
  ROUND_INDEX="$LAST_ROUND"
fi
log "小说 loop 调度器启动：${START_DAY} ${START_AT} -> ${END_DAY} ${END_AT}，统一账号池=${ACCOUNT_POOL}，每轮 ${COUNT} 条，间隔 ${INTERVAL_SECONDS} 秒，续跑起始轮次=${ROUND_INDEX}。"


while true; do
  NOW_EPOCH="$(date +%s)"
  if (( NOW_EPOCH >= END_EPOCH )); then
    log "已到结束时间 ${END_DAY} ${END_AT}，停止小说 loop。"
    break
  fi

  ROUND_INDEX=$((ROUND_INDEX + 1))
  ROUND_ACCOUNT_POOL="$ACCOUNT_POOL"
  ROUND_LABEL="统一二十账号池"

  ROUND_ID="$(printf 'round_%02d' "$ROUND_INDEX")"
  JSON_PATH="$RUN_DIR/${ROUND_ID}.json"
  log "开始 ${ROUND_ID}：账号池=${ROUND_ACCOUNT_POOL}（${ROUND_LABEL}）。"

  ROUND_STATUS="failed"
  if BARRY_NOVEL_DELETE_LOCAL_OUTPUT_AFTER_PUBLISH="$DELETE_LOCAL_OUTPUT" \
    BARRY_VIDEO_TEST_SUMMARY_DIR="$REPORT_DIR" \
    python3 backend/inbeidou_cli.py novels pipeline \
      --execute \
      --publish \
      --count "$COUNT" \
      --publish-platform "$PLATFORM" \
      --account-pool "$ROUND_ACCOUNT_POOL" \
      --json >"$JSON_PATH" 2>>"$LOG_FILE"; then
    ROUND_STATUS="success"
    log "${ROUND_ID} 完成。结果文件：$JSON_PATH"
  else
    log "${ROUND_ID} 返回非零状态，已保留结果文件：$JSON_PATH"
  fi

  rm -rf "${BARRY_VIDEO_NOVEL_DOWNLOAD_DIR:-$HOME/Downloads/barry-video-novels}" "${BARRY_VIDEO_NOVEL_TMP_DIR:-/tmp/barry-video-novels}" 2>/dev/null || true
  log "${ROUND_ID} 已清理服务器小说视频产物目录。"

  NOW_EPOCH="$(date +%s)"
  NEXT_EPOCH=$((NOW_EPOCH + INTERVAL_SECONDS))
  if (( NEXT_EPOCH >= END_EPOCH )); then
    log "下一轮将超过结束时间 ${END_DAY} ${END_AT}，停止小说 loop。"
    break
  fi
  sleep "$INTERVAL_SECONDS"
done
