#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${BARRY_SERVER_ENV_FILE:-$ROOT_DIR/.env.server}"
SUPERVISOR_SCRIPT="$ROOT_DIR/scripts/run-dual-line-supervisor.py"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

for EXTRA_ENV_FILE in "$ROOT_DIR/.env.local" "$ROOT_DIR/.env.task-log.local"; do
  if [[ -f "$EXTRA_ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$EXTRA_ENV_FILE"
    set +a
  fi
done

cd "$ROOT_DIR"

STATE_ROOT="${BARRY_LOOP_STATE_ROOT:-$ROOT_DIR/runtime/continuous-loop}"
INTERVAL_SECONDS="${BARRY_LOOP_CLAUDE_REPORT_INTERVAL_SECONDS:-600}"
REPORT_LINES="${BARRY_LOOP_CLAUDE_REPORT_LINES:-realtime,realtime_single,realtime_day,creative_list,creative_list_day,ordinary,fbhot_test,yourchannel,recent_order,stardusttv,tag_test}"
RUN_ID="$(date '+%Y%m%d-%H%M%S')"
LOG_DIR="${BARRY_LOOP_CLAUDE_REPORT_LOG_DIR:-$STATE_ROOT/claude-reporter-$RUN_ID}"
SUPERVISOR_LOG="$LOG_DIR/supervisor.stdout.log"

mkdir -p "$LOG_DIR"

echo "===== Barry Video 24h loop + Claude reporter 启动 $(date '+%F %T') ====="
echo "ROOT_DIR=$ROOT_DIR"
echo "STATE_ROOT=$STATE_ROOT"
echo "REPORT_LINES=$REPORT_LINES"
echo "INTERVAL_SECONDS=$INTERVAL_SECONDS"
echo "SUPERVISOR_LOG=$SUPERVISOR_LOG"
echo "说明：本脚本会把 10 分钟状态快照直接打印到当前 Claude 终端。"
echo
SUPERVISOR_PID="$(pgrep -fl "run-dual-line-supervisor.py" | awk 'NR==1 {print $1}')"
REPORTER_MODE="attach"
if [[ -z "$SUPERVISOR_PID" ]]; then
  bash "$ROOT_DIR/scripts/run-dual-line-forever.sh" "$@" >"$SUPERVISOR_LOG" 2>&1 &
  SUPERVISOR_PID=$!
  REPORTER_MODE="spawn"
  echo "已启动新的 supervisor pid=${SUPERVISOR_PID}"
else
  echo "检测到现有 supervisor pid=${SUPERVISOR_PID}，直接附着 reporter，不重复启动。"
  SUPERVISOR_LOG="${BARRY_LOOP_CLAUDE_REPORT_ATTACH_LOG:-$ROOT_DIR/runtime/continuous-loop/supervisor.attach.log}"
fi

cleanup() {
  if [[ "$REPORTER_MODE" == "spawn" ]] && [[ -n "${SUPERVISOR_PID:-}" ]] && kill -0 "$SUPERVISOR_PID" >/dev/null 2>&1; then
    echo
    echo "收到退出信号，停止 supervisor pid=${SUPERVISOR_PID} ..."
    kill -TERM "$SUPERVISOR_PID" >/dev/null 2>&1 || true
    wait "$SUPERVISOR_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup INT TERM EXIT

while kill -0 "$SUPERVISOR_PID" >/dev/null 2>&1; do
  echo
  echo "================ Claude 10分钟状态快照 $(date '+%F %T') ================"
  python3 -u "$ROOT_DIR/scripts/monitor-continuous-loop.py" \
    --once \
    --lines "$REPORT_LINES" \
    --state-root "$STATE_ROOT" \
    --day "$(date '+%F')" || true
  echo "supervisor pid=${SUPERVISOR_PID}  log=${SUPERVISOR_LOG}"
  echo "================ 快照结束 ================"
  echo
  sleep "$INTERVAL_SECONDS" &
  wait $! || true
done

wait "$SUPERVISOR_PID"
