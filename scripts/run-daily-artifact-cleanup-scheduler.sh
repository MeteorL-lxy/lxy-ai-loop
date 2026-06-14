#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CLEANUP_AT="${BARRY_DAILY_CLEANUP_AT:-17:30}"
STATE_ROOT="${BARRY_DAILY_CLEANUP_STATE_ROOT:-$ROOT_DIR/data/daily-cleanup}"
PID_FILE="$STATE_ROOT/cleanup.pid"
LOG_FILE="$STATE_ROOT/cleanup.log"
DONE_DIR="$STATE_ROOT/done"
PUSH_NOTICE="${BARRY_FEISHU_DAILY_CLEANUP_PUSH:-1}"

mkdir -p "$STATE_ROOT" "$DONE_DIR"
touch "$LOG_FILE"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG_FILE"
}

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    log "每日清理调度器已在运行，pid=${EXISTING_PID}，跳过重复启动。"
    exit 0
  fi
fi

echo "$$" > "$PID_FILE"
cleanup() {
  rm -f "$PID_FILE"
}
trap cleanup EXIT

cleanup_marker() {
  echo "$DONE_DIR/$1.done"
}

push_cleanup_notice() {
  local day="$1"
  local json_path="$2"
  if [[ "$PUSH_NOTICE" != "1" && "$PUSH_NOTICE" != "true" && "$PUSH_NOTICE" != "yes" && "$PUSH_NOTICE" != "on" ]]; then
    return 0
  fi

  CLEANUP_DAY="$day" CLEANUP_JSON_PATH="$json_path" python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "backend")
import flywheel_cli as f  # type: ignore

day = str(os.getenv("CLEANUP_DAY") or "").strip() or "-"
json_path = Path(str(os.getenv("CLEANUP_JSON_PATH") or "").strip())
payload = {}
if json_path.exists():
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}

deleted_failed = int(payload.get("deleted_failed_publish_files") or 0)
deleted_old_drama = int(payload.get("deleted_old_drama_clip_files") or 0)
deleted_reports = int(payload.get("deleted_report_files") or 0)
deleted_novel = int(payload.get("deleted_novel_artifact_roots") or 0)
cleanup = payload.get("cleanup") if isinstance(payload.get("cleanup"), dict) else {}
failed_errors = (cleanup.get("failed_publish") or {}).get("errors") if isinstance(cleanup.get("failed_publish"), dict) else []
old_drama_errors = (cleanup.get("old_drama_clips") or {}).get("errors") if isinstance(cleanup.get("old_drama_clips"), dict) else []
report_errors = (cleanup.get("reports") or {}).get("errors") if isinstance(cleanup.get("reports"), dict) else []
novel_errors = (cleanup.get("novel_artifacts") or {}).get("errors") if isinstance(cleanup.get("novel_artifacts"), dict) else []
error_count = len(failed_errors or []) + len(old_drama_errors or []) + len(report_errors or []) + len(novel_errors or [])
summary = str(payload.get("user_summary_zh") or "").strip()
message = (
    f"Barry 每日清理已完成：日期 {day}，删除未发布成片 {deleted_failed} 个，"
    f"删除历史短剧成片 {deleted_old_drama} 个，删除残留报告 {deleted_reports} 个，"
    f"删除小说中间产物目录 {deleted_novel} 个，异常 {error_count} 个。"
)
if summary:
    message += f" {summary}"

token = f._feishu_get_tenant_access_token()
receive_id_type, receive_id = f._feishu_receive_target()
result = f._feishu_send_text_message(
    token,
    receive_id_type=receive_id_type,
    receive_id=receive_id,
    text=message,
)
print(str(result.get("message_id") or ""))
PY
}

date_plus_days() {
  python3 - "$1" "$2" <<'PY'
from datetime import datetime, timedelta
import sys

day = datetime.strptime(sys.argv[1], "%Y-%m-%d")
offset = int(sys.argv[2])
print((day + timedelta(days=offset)).strftime("%F"))
PY
}

cleanup_epoch_for_day() {
  python3 - "$1" "$CLEANUP_AT" <<'PY'
from datetime import datetime
import sys

day = datetime.strptime(sys.argv[1], "%Y-%m-%d")
hour, minute = map(int, sys.argv[2].split(":"))
target = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
print(int(target.timestamp()))
PY
}

run_cleanup() {
  local day="$1"
  local marker json_path
  marker="$(cleanup_marker "$day")"
  if [[ -f "$marker" ]]; then
    return 0
  fi

  log "开始执行每日清理，日期=${day}，时间点=${CLEANUP_AT}。"
  json_path="$STATE_ROOT/$day.json"
  if python3 backend/flywheel_cli.py cleanup-daily-artifacts >"$json_path" 2>>"$LOG_FILE"; then
    :
  else
    log "每日清理命令返回非零状态，继续读取结果文件。"
  fi

  python3 - "$json_path" <<'PY' | tee -a "$LOG_FILE"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {}
if path.exists():
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}

summary = str(payload.get("user_summary_zh") or "").strip()
if summary:
    print(summary)
print(f"未发布成片删除：{int(payload.get('deleted_failed_publish_files') or 0)} 个")
print(f"历史短剧成片删除：{int(payload.get('deleted_old_drama_clip_files') or 0)} 个")
print(f"报告文件删除：{int(payload.get('deleted_report_files') or 0)} 个")
print(f"小说中间产物目录删除：{int(payload.get('deleted_novel_artifact_roots') or 0)} 个")
PY

  if message_id="$(push_cleanup_notice "$day" "$json_path" 2>>"$LOG_FILE")"; then
    if [[ -n "$message_id" ]]; then
      log "每日清理通知已发送，message_id=${message_id}。"
    else
      log "每日清理通知发送完成。"
    fi
  else
    log "每日清理通知发送失败。"
  fi

  touch "$marker"
}

log "每日清理调度器启动。时间点=${CLEANUP_AT}。"

while true; do
  today="$(date +%F)"
  marker="$(cleanup_marker "$today")"

  if [[ -f "$marker" ]]; then
    tomorrow="$(date_plus_days "$today" 1)"
    target_epoch="$(cleanup_epoch_for_day "$tomorrow")"
  else
    target_epoch="$(cleanup_epoch_for_day "$today")"
  fi

  now_epoch="$(date +%s)"
  if (( now_epoch >= target_epoch )) && [[ ! -f "$marker" ]]; then
    run_cleanup "$today"
    continue
  fi

  sleep_seconds=$((target_epoch - now_epoch))
  if (( sleep_seconds > 0 )); then
    sleep "$sleep_seconds"
  else
    sleep 30
  fi
done
