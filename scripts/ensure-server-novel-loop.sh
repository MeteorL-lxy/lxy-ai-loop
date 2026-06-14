#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/runtime/novel-loop"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/ensure.log"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" >>"$LOG_FILE"
}

if pgrep -f "run-novel-loop-scheduler.sh" >/dev/null 2>&1; then
  log "小说 loop 调度器已在运行，跳过。"
  exit 0
fi

if pgrep -f "inbeidou_cli.py novels pipeline --execute --publish" >/dev/null 2>&1; then
  log "检测到小说 pipeline 正在执行，暂不重复拉起调度器。"
  exit 0
fi

log "未发现小说 loop 调度器，准备拉起。"
nohup "$ROOT_DIR/scripts/run-server-novel-loop.sh" >>"$LOG_DIR/nohup.out" 2>&1 &
sleep 2

if pgrep -f "run-novel-loop-scheduler.sh" >/dev/null 2>&1; then
  log "小说 loop 调度器已成功拉起。"
  exit 0
fi

log "小说 loop 调度器拉起失败。"
exit 1
