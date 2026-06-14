#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PLATFORM="${BARRY_LOOP_PLATFORM:-FACEBOOK}"
COUNT="${BARRY_LOOP_COUNT:-0}"
ACCOUNT_SUCCESS_TARGET="${BARRY_LOOP_ACCOUNT_SUCCESS_TARGET:-10}"
MIN_GOAL_SUCCESS_RATIO="${BARRY_LOOP_MIN_GOAL_SUCCESS_RATIO:-0.95}"
TOTAL_SUCCESS_GOAL="${BARRY_LOOP_TOTAL_SUCCESS_GOAL:-500}"
MIN_TOTAL_SUCCESS="${BARRY_LOOP_MIN_TOTAL_SUCCESS:-475}"
ROUND_TIMES_CSV="${BARRY_LOOP_ROUND_TIMES:-18:00,18:20,18:40,19:00,19:20,19:40,20:00}"
IFS=',' read -r -a ROUND_TIMES <<< "$ROUND_TIMES_CSV"
ROUND_TIMES=("${ROUND_TIMES[@]/# /}")
MAX_ROUNDS="${BARRY_LOOP_MAX_ROUNDS:-${#ROUND_TIMES[@]}}"
if (( MAX_ROUNDS > ${#ROUND_TIMES[@]} )); then
  MAX_ROUNDS="${#ROUND_TIMES[@]}"
fi
MAX_EXTRA_ROUNDS="${BARRY_LOOP_MAX_EXTRA_ROUNDS:-99}"
MAX_TOTAL_REQUESTS="${BARRY_LOOP_MAX_TOTAL_REQUESTS:-1800}"
ACCOUNT_POOL="${BARRY_LOOP_ACCOUNT_POOL:-}"
SPLIT_SHORT_DRAMA_LINES="${BARRY_LOOP_SPLIT_SHORT_DRAMA_LINES:-1}"
REALTIME_ACCOUNT_POOL="${BARRY_LOOP_REALTIME_ACCOUNT_POOL:-facebook_drama_realtime_pool}"
ORDINARY_ACCOUNT_POOL="${BARRY_LOOP_ORDINARY_ACCOUNT_POOL:-facebook_drama_ordinary_pool}"
REPORT_DIR="${BARRY_LOOP_REPORT_DIR:-/Users/xinyuliu/Downloads/AI Loop/测试总结}"
STATE_ROOT="${BARRY_LOOP_STATE_ROOT:-$ROOT_DIR/data/daily-loop}"
ALLOW_ACCOUNT_REUSE="${BARRY_LOOP_ALLOW_ACCOUNT_REUSE:-1}"
PUSH_DAILY_REPORT="${BARRY_FEISHU_DAILY_LOOP_REPORT_PUSH:-1}"
PUSH_ROUND_NOTICE="${BARRY_FEISHU_DAILY_LOOP_ROUND_NOTICE_PUSH:-1}"
DAILY_REPORT_DELAY_SECONDS="${BARRY_FEISHU_DAILY_LOOP_REPORT_DELAY_SECONDS:-3600}"
DELETE_REPORT_AFTER_PUSH="${BARRY_FEISHU_DELETE_LOCAL_REPORT_AFTER_PUSH:-0}"

TODAY="$(date +%F)"
RUN_DIR="$STATE_ROOT/$TODAY"
PID_FILE="$RUN_DIR/scheduler.pid"
LOG_FILE="$RUN_DIR/scheduler.log"
REPORT_FILE="$REPORT_DIR/短剧日常自动发布报告_$(date +%Y%m%d).md"

mkdir -p "$RUN_DIR" "$REPORT_DIR"
touch "$LOG_FILE"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG_FILE"
}

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_live_scheduler_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  local cmdline=""
  if [[ -r "/proc/$pid/cmdline" ]]; then
    cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
  else
    cmdline="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  fi
  [[ "$cmdline" == *"run-daily-loop-scheduler.sh"* ]]
}

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if is_live_scheduler_pid "$EXISTING_PID"; then
    log "今日调度器已在运行，pid=${EXISTING_PID}，跳过重复启动。"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

echo "$$" > "$PID_FILE"
cleanup() {
  rm -f "$PID_FILE"
}
FINAL_REPORT_SENT=0
finalize_daily_report() {
  local exit_status="${1:-0}"
  if (( FINAL_REPORT_SENT == 1 )); then
    return 0
  fi
  FINAL_REPORT_SENT=1
  write_daily_report
  if (( DAILY_REPORT_DELAY_SECONDS > 0 )); then
    log "本次调度已结束（exit=${exit_status}），等待 ${DAILY_REPORT_DELAY_SECONDS} 秒后推送今日总测试报告。"
    sleep "$DAILY_REPORT_DELAY_SECONDS"
    write_daily_report
  fi
  if message_id="$(push_daily_report 2>>"$LOG_FILE")"; then
    if [[ -n "$message_id" ]]; then
      log "今日测试报告已推送到飞书，message_id=${message_id}。"
      delete_daily_reports_after_push
    fi
  else
    log "今日测试报告飞书推送失败，详情见日志。"
  fi
}
on_exit() {
  local exit_status=$?
  finalize_daily_report "$exit_status"
  cleanup
  if (( exit_status == 0 )); then
    log "今日调度器结束。累计成功 $(sum_success) 条，请求总数 $(sum_requested) 条，失败 $(sum_failed) 条，未提交 $(sum_unsubmitted) 条。"
  else
    log "今日调度器异常结束（exit=${exit_status}）。累计成功 $(sum_success) 条，请求总数 $(sum_requested) 条，失败 $(sum_failed) 条，未提交 $(sum_unsubmitted) 条。"
  fi
  exit "$exit_status"
}
trap on_exit EXIT

round_label() {
  local name="$1"
  if [[ "$name" =~ ^round([0-9]+)$ ]]; then
    echo "第 ${BASH_REMATCH[1]} 轮"
    return 0
  fi
  if [[ "$name" =~ ^extra([0-9]+)$ ]]; then
    echo "补量第 ${BASH_REMATCH[1]} 轮"
    return 0
  fi
  echo "$name"
}

round_time() {
  local name="$1"
  if [[ "$name" =~ ^round([0-9]+)$ ]]; then
    local idx=$((BASH_REMATCH[1] - 1))
    if (( idx >= 0 && idx < ${#ROUND_TIMES[@]} )); then
      echo "${ROUND_TIMES[$idx]}"
      return 0
    fi
  fi
  echo ""
}

round_summary_path() {
  echo "$RUN_DIR/$1.summary"
}

round_done() {
  [[ -f "$(round_summary_path "$1")" ]]
}

current_hhmm() {
  date +%H:%M
}

account_target_status_json() {
  python3 - "$ROOT_DIR" "$RUN_DIR" "$ACCOUNT_POOL" "$PLATFORM" "$ACCOUNT_SUCCESS_TARGET" <<'PY'
import json
import sys
from pathlib import Path

root_dir = Path(sys.argv[1]).resolve()
run_dir = Path(sys.argv[2]).resolve()
pool_name = sys.argv[3]
platform = sys.argv[4]
account_success_target = int(sys.argv[5])

sys.path.insert(0, str(root_dir / "backend"))
from flywheel.daily_loop_targets import get_pool_target_status

payload = get_pool_target_status(
    root_dir=root_dir,
    run_dir=run_dir,
    pool_name=pool_name,
    platform=platform,
    account_success_target=account_success_target,
)
print(json.dumps(payload, ensure_ascii=False))
PY
}

pool_target_status_json() {
  local pool_name="$1"
  python3 - "$ROOT_DIR" "$RUN_DIR" "$pool_name" "$PLATFORM" "$ACCOUNT_SUCCESS_TARGET" <<'PY'
import json
import sys
from pathlib import Path

root_dir = Path(sys.argv[1]).resolve()
run_dir = Path(sys.argv[2]).resolve()
pool_name = sys.argv[3]
platform = sys.argv[4]
account_success_target = int(sys.argv[5])

sys.path.insert(0, str(root_dir / "backend"))
from flywheel.daily_loop_targets import get_pool_target_status

payload = get_pool_target_status(
    root_dir=root_dir,
    run_dir=run_dir,
    pool_name=pool_name,
    platform=platform,
    account_success_target=account_success_target,
)
print(json.dumps(payload, ensure_ascii=False))
PY
}

account_target_field() {
  local field="$1"
  local payload
  payload="$(account_target_status_json)"
  python3 - "$payload" "$field" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
field = sys.argv[2]
value = payload.get(field, "")
if isinstance(value, list):
    print(",".join(str(item) for item in value))
else:
    print(value)
PY
}

pool_target_field() {
  local pool_name="$1"
  local field="$2"
  local payload
  payload="$(pool_target_status_json "$pool_name")"
  python3 - "$payload" "$field" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
field = sys.argv[2]
value = payload.get(field, "")
if isinstance(value, list):
    print(",".join(str(item) for item in value))
else:
    print(value)
PY
}

resolved_round_request_cap() {
  local eligible_count configured_count
  eligible_count="$(account_target_field eligible_pool_size)"
  configured_count="${COUNT:-0}"
  if [[ ! "$eligible_count" =~ ^[0-9]+$ ]] || (( eligible_count < 1 )); then
    eligible_count=1
  fi
  if [[ "$configured_count" =~ ^[0-9]+$ ]] && (( configured_count > 0 )); then
    if (( configured_count < eligible_count )); then
      echo "$configured_count"
    else
      echo "$eligible_count"
    fi
    return 0
  fi
  echo "$eligible_count"
}

minimum_goal_success() {
  python3 - "$ROOT_DIR" "$RUN_DIR" "$ACCOUNT_POOL" "$PLATFORM" "$ACCOUNT_SUCCESS_TARGET" "$MIN_GOAL_SUCCESS_RATIO" "$TOTAL_SUCCESS_GOAL" "$MIN_TOTAL_SUCCESS" <<'PY'
import math
import sys
from pathlib import Path

root_dir = Path(sys.argv[1]).resolve()
run_dir = Path(sys.argv[2]).resolve()
pool_name = sys.argv[3]
platform = sys.argv[4]
account_success_target = int(sys.argv[5])
minimum_ratio = float(sys.argv[6])
total_success_goal = int(sys.argv[7])
minimum_total_success = int(sys.argv[8])

sys.path.insert(0, str(root_dir / "backend"))
from flywheel.daily_loop_targets import get_pool_target_status

payload = get_pool_target_status(
    root_dir=root_dir,
    run_dir=run_dir,
    pool_name=pool_name,
    platform=platform,
    account_success_target=account_success_target,
)
target_total = int(payload.get("target_total_success") or 0)
if total_success_goal > 0:
    target_total = total_success_goal
minimum_success = int(math.ceil(target_total * minimum_ratio)) if target_total > 0 else 0
if minimum_total_success > 0:
    minimum_success = minimum_total_success
print(minimum_success)
PY
}

effective_target_total_success() {
  python3 - "$ROOT_DIR" "$RUN_DIR" "$ACCOUNT_POOL" "$PLATFORM" "$ACCOUNT_SUCCESS_TARGET" "$TOTAL_SUCCESS_GOAL" <<'PY'
import sys
from pathlib import Path

root_dir = Path(sys.argv[1]).resolve()
run_dir = Path(sys.argv[2]).resolve()
pool_name = sys.argv[3]
platform = sys.argv[4]
account_success_target = int(sys.argv[5])
total_success_goal = int(sys.argv[6])

sys.path.insert(0, str(root_dir / "backend"))
from flywheel.daily_loop_targets import get_pool_target_status

payload = get_pool_target_status(
    root_dir=root_dir,
    run_dir=run_dir,
    pool_name=pool_name,
    platform=platform,
    account_success_target=account_success_target,
)
target_total = int(payload.get("target_total_success") or 0)
if total_success_goal > 0:
    target_total = total_success_goal
print(target_total)
PY
}

effective_remaining_success_deficit() {
  local total_success minimum_success deficit
  total_success="$(sum_success)"
  minimum_success="$(minimum_goal_success)"
  if [[ ! "$total_success" =~ ^[0-9]+$ ]]; then
    total_success=0
  fi
  if [[ ! "$minimum_success" =~ ^[0-9]+$ ]]; then
    minimum_success=0
  fi
  deficit=$((minimum_success - total_success))
  if (( deficit < 0 )); then
    deficit=0
  fi
  echo "$deficit"
}

effective_max_total_requests() {
  python3 - "$ROOT_DIR" "$RUN_DIR" "$ACCOUNT_POOL" "$PLATFORM" "$ACCOUNT_SUCCESS_TARGET" "$MIN_GOAL_SUCCESS_RATIO" "$COUNT" "$MAX_TOTAL_REQUESTS" "$TOTAL_SUCCESS_GOAL" "$MIN_TOTAL_SUCCESS" <<'PY'
import math
import sys
from pathlib import Path

root_dir = Path(sys.argv[1]).resolve()
run_dir = Path(sys.argv[2]).resolve()
pool_name = sys.argv[3]
platform = sys.argv[4]
account_success_target = int(sys.argv[5])
minimum_ratio = float(sys.argv[6])
configured_count = int(sys.argv[7])
configured_budget = int(sys.argv[8])
total_success_goal = int(sys.argv[9])
minimum_total_success = int(sys.argv[10])
minimum_rate_pct = 35

sys.path.insert(0, str(root_dir / "backend"))
from flywheel.daily_loop_targets import get_pool_target_status

payload = get_pool_target_status(
    root_dir=root_dir,
    run_dir=run_dir,
    pool_name=pool_name,
    platform=platform,
    account_success_target=account_success_target,
)
target_total = int(payload.get("target_total_success") or 0)
if total_success_goal > 0:
    target_total = total_success_goal
eligible_pool_size = max(int(payload.get("eligible_pool_size") or 0), 1)
count = configured_count if configured_count > 0 else eligible_pool_size
count = max(1, min(count, eligible_pool_size))
minimum_success = int(math.ceil(target_total * minimum_ratio))
if minimum_total_success > 0:
    minimum_success = minimum_total_success
required_budget = int(math.ceil(minimum_success * 100 / minimum_rate_pct)) if minimum_success > 0 else 0
if required_budget > 0:
    required_budget = int(math.ceil(required_budget / count) * count)
effective_budget = max(configured_budget, required_budget)
print(effective_budget)
PY
}

round_target_epoch() {
  python3 - "$TODAY" "$ROUND_TIMES_CSV" "$1" <<'PY'
from datetime import datetime, timedelta
import sys

anchor_day = datetime.strptime(sys.argv[1], "%Y-%m-%d")
round_times = [item.strip() for item in sys.argv[2].split(",") if item.strip()]
name = sys.argv[3]
if name.startswith("extra"):
    print(int(datetime.now().timestamp()))
    raise SystemExit(0)
idx = int(name.replace("round", "")) - 1
first_h, first_m = map(int, round_times[0].split(":"))
target_h, target_m = map(int, round_times[idx].split(":"))
target_day = anchor_day if (target_h, target_m) >= (first_h, first_m) else anchor_day + timedelta(days=1)
target = target_day.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
print(int(target.timestamp()))
PY
}

round_scheduled_datetime() {
  python3 - "$TODAY" "$ROUND_TIMES_CSV" "$1" <<'PY'
from datetime import datetime, timedelta
import sys

anchor_day = datetime.strptime(sys.argv[1], "%Y-%m-%d")
round_times = [item.strip() for item in sys.argv[2].split(",") if item.strip()]
name = sys.argv[3]
if name.startswith("extra"):
    print(datetime.now().strftime("%F %T"))
    raise SystemExit(0)
idx = int(name.replace("round", "")) - 1
first_h, first_m = map(int, round_times[0].split(":"))
target_h, target_m = map(int, round_times[idx].split(":"))
target_day = anchor_day if (target_h, target_m) >= (first_h, first_m) else anchor_day + timedelta(days=1)
target = target_day.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
print(target.strftime("%F %T"))
PY
}

sum_success() {
  local total=0
  local summary
  for summary in "$RUN_DIR"/*.summary; do
    [[ -f "$summary" ]] || continue
    local value
    value="$(awk -F= '$1=="success_count"{print $2}' "$summary" 2>/dev/null || true)"
    if [[ "$value" =~ ^[0-9]+$ ]]; then
      total=$((total + value))
    fi
  done
  echo "$total"
}

sum_requested() {
  local total=0
  local summary
  for summary in "$RUN_DIR"/*.summary; do
    [[ -f "$summary" ]] || continue
    local value
    value="$(awk -F= '$1=="requested_count"{print $2}' "$summary" 2>/dev/null || true)"
    if [[ "$value" =~ ^[0-9]+$ ]]; then
      total=$((total + value))
    fi
  done
  echo "$total"
}

sum_failed() {
  local total=0
  local summary
  for summary in "$RUN_DIR"/*.summary; do
    [[ -f "$summary" ]] || continue
    local value
    value="$(awk -F= '$1=="failed_count"{print $2}' "$summary" 2>/dev/null || true)"
    if [[ "$value" =~ ^[0-9]+$ ]]; then
      total=$((total + value))
    fi
  done
  echo "$total"
}

sum_unsubmitted() {
  local total=0
  local summary
  for summary in "$RUN_DIR"/*.summary; do
    [[ -f "$summary" ]] || continue
    local value
    value="$(awk -F= '$1=="unsubmitted_count"{print $2}' "$summary" 2>/dev/null || true)"
    if [[ "$value" =~ ^[0-9]+$ ]]; then
      total=$((total + value))
    fi
  done
  echo "$total"
}

next_round_request_count() {
  local round="$1"
  local total_success total_requested remaining_request_budget rate_pct recommended count budget_cap round_cap
  local remaining_deficit unmet_account_count round_no remaining_rounds per_round_success_target
  total_success="$(sum_success)"
  total_requested="$(sum_requested)"
  remaining_deficit="$(effective_remaining_success_deficit)"
  unmet_account_count="$(account_target_field unmet_account_count)"
  if [[ ! "$remaining_deficit" =~ ^[0-9]+$ ]]; then
    remaining_deficit=0
  fi
  if [[ ! "$unmet_account_count" =~ ^[0-9]+$ ]]; then
    unmet_account_count=0
  fi
  if (( remaining_deficit <= 0 )); then
    echo 0
    return 0
  fi
  budget_cap="$(effective_max_total_requests)"
  if (( budget_cap > 0 )); then
    remaining_request_budget=$((budget_cap - total_requested))
    if (( remaining_request_budget <= 0 )); then
      echo 0
      return 0
    fi
  else
    remaining_request_budget=0
  fi
  rate_pct=65
  if (( total_requested > 0 && total_success > 0 )); then
    rate_pct=$(( total_success * 100 / total_requested ))
    if (( rate_pct < 35 )); then
      rate_pct=35
    fi
    if (( rate_pct > 100 )); then
      rate_pct=100
    fi
  fi
  round_no="${round#round}"
  remaining_rounds=$((MAX_ROUNDS - round_no + 1))
  if (( remaining_rounds < 1 )); then
    remaining_rounds=1
  fi
  per_round_success_target=$(( (remaining_deficit + remaining_rounds - 1) / remaining_rounds ))
  recommended=$(( (per_round_success_target * 100 + rate_pct - 1) / rate_pct ))
  round_cap="$(resolved_round_request_cap)"
  count="$round_cap"
  if (( count < unmet_account_count )); then
    count=$unmet_account_count
  fi
  if (( remaining_request_budget > 0 && count > remaining_request_budget )); then
    count=$remaining_request_budget
  fi
  if (( count > recommended )); then
    count=$recommended
  fi
  if (( count < 1 )); then
    count=1
  fi
  echo "$count"
}

select_round_account_ids() {
  local requested_count="$1"
  select_round_account_ids_for_pool "$ACCOUNT_POOL" "$requested_count"
}

select_round_account_ids_for_pool() {
  local pool_name="$1"
  local requested_count="$2"
  python3 - "$ROOT_DIR" "$RUN_DIR" "$pool_name" "$PLATFORM" "$requested_count" "$ALLOW_ACCOUNT_REUSE" <<'PY'
import json
import sys
from pathlib import Path

root_dir = Path(sys.argv[1]).resolve()
run_dir = Path(sys.argv[2]).resolve()
pool_name = sys.argv[3]
platform = sys.argv[4]
requested_count = int(sys.argv[5])
allow_reuse = str(sys.argv[6]).strip() in {"1", "true", "yes", "on"}

sys.path.insert(0, str(root_dir / "backend"))
from flywheel.daily_loop_targets import select_balanced_account_ids

payload = select_balanced_account_ids(
    root_dir=root_dir,
    run_dir=run_dir,
    pool_name=pool_name,
    platform=platform,
    requested_count=requested_count,
    allow_reuse=allow_reuse,
)
print(json.dumps(payload, ensure_ascii=False))
PY
}

split_round_line_plan() {
  local requested_count="$1"
  python3 - "$requested_count" "$SPLIT_SHORT_DRAMA_LINES" "$REALTIME_ACCOUNT_POOL" "$ORDINARY_ACCOUNT_POOL" "$(pool_target_field "$REALTIME_ACCOUNT_POOL" eligible_pool_size)" "$(pool_target_field "$ORDINARY_ACCOUNT_POOL" eligible_pool_size)" <<'PY'
import json
import sys

requested_count = int(sys.argv[1] or 0)
split_enabled = str(sys.argv[2]).strip().lower() in {"1", "true", "yes", "on"}
realtime_pool = str(sys.argv[3] or "").strip()
ordinary_pool = str(sys.argv[4] or "").strip()
realtime_eligible = int(sys.argv[5] or 0)
ordinary_eligible = int(sys.argv[6] or 0)

if not split_enabled:
    print(json.dumps({"split_enabled": False, "lines": []}, ensure_ascii=False))
    raise SystemExit(0)

realtime_requested = min(max(requested_count, 0), max(realtime_eligible, 0))
ordinary_requested = max(requested_count - realtime_requested, 0)
if ordinary_eligible > 0:
    ordinary_requested = min(ordinary_requested, ordinary_eligible)
else:
    ordinary_requested = 0

payload = {
    "split_enabled": True,
    "lines": [
        {
            "line_name": "realtime",
            "pool_name": realtime_pool,
            "requested_count": realtime_requested,
            "eligible_pool_size": realtime_eligible,
            "realtime_rank_enabled": True,
        },
        {
            "line_name": "ordinary",
            "pool_name": ordinary_pool,
            "requested_count": ordinary_requested,
            "eligible_pool_size": ordinary_eligible,
            "realtime_rank_enabled": False,
        },
    ],
}
print(json.dumps(payload, ensure_ascii=False))
PY
}

write_daily_report() {
  python3 - "$ROOT_DIR" "$RUN_DIR" "$REPORT_FILE" "$TODAY" "$PLATFORM" "$COUNT" "$ACCOUNT_POOL" "$ACCOUNT_SUCCESS_TARGET" "$MAX_ROUNDS" "$MAX_EXTRA_ROUNDS" "$MAX_TOTAL_REQUESTS" "$MIN_GOAL_SUCCESS_RATIO" "$TOTAL_SUCCESS_GOAL" "$MIN_TOTAL_SUCCESS" <<'PY'
import json
import os
import sys
from pathlib import Path
import math
from collections import Counter

root_dir = Path(sys.argv[1])
run_dir = Path(sys.argv[2])
report_file = Path(sys.argv[3])
today = sys.argv[4]
platform = sys.argv[5]
configured_count = int(sys.argv[6])
account_pool = sys.argv[7]
account_target = int(sys.argv[8])
base_rounds = int(sys.argv[9])
max_extra_rounds = int(sys.argv[10])
max_total_requests = int(sys.argv[11])
minimum_ratio = float(sys.argv[12])
configured_target_total = int(sys.argv[13])
configured_min_total = int(sys.argv[14])

sys.path.insert(0, str(root_dir / "backend"))
from flywheel.daily_loop_targets import get_pool_target_status

rows = []
for path in sorted(run_dir.glob("*.summary")):
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    if data:
        data["_summary_file"] = path.name
        rows.append(data)

def as_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default

counted_statuses = {"done", "blocked", "error"}
total_requested = sum(as_int(row.get("requested_count", "0")) for row in rows if row.get("status") in counted_statuses)
total_success = sum(as_int(row.get("success_count", "0")) for row in rows if row.get("status") in counted_statuses)
total_failed = sum(as_int(row.get("failed_count", "0")) for row in rows if row.get("status") in counted_statuses)
total_unsubmitted = sum(as_int(row.get("unsubmitted_count", "0")) for row in rows if row.get("status") in counted_statuses)

def load_round_payload(round_name: str) -> dict:
    json_path = run_dir / f"{round_name}.json"
    if not json_path.exists():
        return {}
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}

def normalize_reason(value: object) -> str:
    text = str(value or "").strip()
    return text or "未分类"

failure_reason_counter: Counter[str] = Counter()
safety_reason_counter: Counter[str] = Counter()
failed_accounts: list[str] = []
abnormal_rounds: list[str] = []
safety_rejected_total = 0
for row in rows:
    status = str(row.get("status") or "").strip()
    if status == "error":
        abnormal_rounds.append(
            f"{row.get('label') or row.get('round') or '-'}：{row.get('note') or '异常结束'}"
            f"（请求 {as_int(row.get('requested_count', '0'))} 条，未提交 {as_int(row.get('unsubmitted_count', '0'))} 条）"
        )
    payload = load_round_payload(str(row.get("round") or ""))
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    failed_tasks = report.get("发布失败任务") if isinstance(report.get("发布失败任务"), list) else []
    for item in failed_tasks:
        if not isinstance(item, dict):
            continue
        failure_reason_counter[normalize_reason(item.get("失败原因") or item.get("错误"))] += 1
        account = str(item.get("账号") or "").strip()
        if account and account not in {"-", ""} and account not in failed_accounts:
            failed_accounts.append(account)
    safety_gate = report.get("安全门槛") if isinstance(report.get("安全门槛"), dict) else {}
    rejected_items = safety_gate.get("拦截明细") if isinstance(safety_gate.get("拦截明细"), list) else []
    if not rejected_items:
        rejected_items = safety_gate.get("拦截预览") if isinstance(safety_gate.get("拦截预览"), list) else []
    for item in rejected_items:
        if not isinstance(item, dict):
            continue
        safety_rejected_total += 1
        safety_reason_counter[normalize_reason(item.get("失败原因") or item.get("原因") or item.get("错误") or item.get("名称"))] += 1

def top_counter_text(counter: Counter[str], *, limit: int = 3) -> str:
    return "、".join(f"{reason} {count} 次" for reason, count in counter.most_common(limit) if count > 0)

failure_summary: list[str] = []
if total_failed > 0 or failure_reason_counter:
    line = f"发布失败共 {total_failed} 条"
    if failed_accounts:
        line += f"，涉及失败账号 {len(failed_accounts)} 个"
    reason_text = top_counter_text(failure_reason_counter)
    if reason_text:
        line += f"；主要原因：{reason_text}"
    line += "。"
    failure_summary.append(line)
if safety_rejected_total > 0 or safety_reason_counter:
    line = f"安全门槛拦截共 {safety_rejected_total} 条"
    reason_text = top_counter_text(safety_reason_counter)
    if reason_text:
        line += f"；主要原因：{reason_text}"
    line += "。"
    failure_summary.append(line)
if abnormal_rounds:
    failure_summary.append("异常轮次：" + "；".join(abnormal_rounds[:5]) + "。")
target_status = get_pool_target_status(
    root_dir=root_dir,
    run_dir=run_dir,
    pool_name=account_pool,
    platform=platform,
    account_success_target=account_target,
)
eligible_accounts = int(target_status.get("eligible_pool_size") or 0)
count = configured_count if configured_count > 0 else max(eligible_accounts, 1)
count = min(count, max(eligible_accounts, 1))
remaining_deficit = int(target_status.get("remaining_success_deficit") or 0)
target_total = int(target_status.get("target_total_success") or 0)
if configured_target_total > 0:
    target_total = configured_target_total
min_account_success = int(target_status.get("min_success_count") or 0)
unmet_account_count = int(target_status.get("unmet_account_count") or 0)
minimum_success = int(math.ceil(target_total * minimum_ratio)) if target_total > 0 else 0
if configured_min_total > 0:
    minimum_success = configured_min_total
remaining_deficit = max(minimum_success - total_success, 0)
minimum_budget = int(math.ceil(minimum_success * 100 / 35)) if minimum_success > 0 else 0
if minimum_budget > 0 and count > 0:
    minimum_budget = int(math.ceil(minimum_budget / count) * count)
effective_budget = max(max_total_requests, minimum_budget)
effective_extra_rounds = max_extra_rounds if max_extra_rounds > 0 else "按缺口持续补量"
actual_success_ratio = (total_success / target_total * 100) if target_total > 0 else 0.0

lines = [
    "# 短剧日常自动发布报告",
    "",
    f"**日期**: {today}",
    f"**目标平台**: {platform}",
    f"**计划目标**: 账号池 {account_pool} 中每个可用账号至少成功发布 {account_target} 条；日总目标成功 {target_total} 条",
    f"**最低成功底线**: 当日累计成功至少达到目标总成功数的 {minimum_ratio * 100:.0f}%（{minimum_success} 条）",
    f"**调度策略**: 每轮最多请求 {count} 条；前 {base_rounds} 轮为基础轮；按账号成功缺口补量，直到所有可用账号达标。",
    f"**保险丝**: 补量轮上限 {effective_extra_rounds}；单日请求预算 {effective_budget} 条。",
    "",
    "---",
    "",
    "## 总体概览",
    "",
    "| 指标 | 数值 |",
    "| --- | --- |",
    f"| 已执行轮次 | {sum(1 for row in rows if row.get('status') in counted_statuses)} 轮 |",
    f"| 可用账号数 | {eligible_accounts} 个 |",
    f"| 每账号目标 | {account_target} 条 |",
    f"| 目标总成功数 | {target_total} 条 |",
    f"| 最低成功底线 | {minimum_success} 条 |",
    f"| 累计请求发布数 | {total_requested} 条 |",
    f"| 累计发布成功 | {total_success} 条 |",
    f"| 当前达成率 | {actual_success_ratio:.1f}% |",
    f"| 累计发布失败 | {total_failed} 条 |",
    f"| 累计未提交 | {total_unsubmitted} 条 |",
    f"| 当前最低账号成功数 | {min_account_success} 条 |",
    f"| 未达标账号数 | {unmet_account_count} 个 |",
    f"| 剩余成功缺口 | {remaining_deficit} 条 |",
    "",
    "## 各轮结果",
    "",
    "| 轮次 | 结果 | 计划时间 | 实际开始 | 请求数 | 成功 | 失败 | 未提交 | 备注 | 报告文件 |",
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
]

for row in rows:
    label = row.get("label", row.get("round", ""))
    lines.append(
        "| {label} | {status_label} | {scheduled} | {started} | {requested} | {success} | {failed} | {unsubmitted} | {note} | {report} |".format(
            label=label,
            status_label=row.get("status_label", row.get("status", "")),
            scheduled=row.get("scheduled_time", ""),
            started=row.get("started_at", ""),
            requested=row.get("requested_count", "-"),
            success=row.get("success_count", "-"),
            failed=row.get("failed_count", "-"),
            unsubmitted=row.get("unsubmitted_count", "-"),
            note=row.get("note", ""),
            report=row.get("report_file", ""),
        )
    )

if failure_summary:
    lines.extend(["", "## 失败情况总结", ""])
    lines.extend(f"- {item}" for item in failure_summary)

lines.extend(
    [
        "",
        "## 结论",
        "",
        (
            f"- 当前累计成功 {total_success} 条，账号池可用账号 {eligible_accounts} 个，每账号目标 {account_target} 条，日总目标 {target_total} 条。"
            + ("已达到今日最低成功底线，今日停止继续发布。" if remaining_deficit <= 0 else f"尚未达到今日最低成功底线，剩余成功缺口 {remaining_deficit} 条。")
        ),
        (
            f"- 当日最低成功底线为 {minimum_success} 条，当前达成率 {actual_success_ratio:.1f}%。"
            + ("已达到 95% 成功底线。" if total_success >= minimum_success else "尚未达到 95% 成功底线，需要继续补量。")
        ),
        "- 详细单轮任务明细仍以各次批量发布测试报告为准。",
    ]
)

report_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY
}

push_daily_report() {
  if [[ "$PUSH_DAILY_REPORT" != "1" && "$PUSH_DAILY_REPORT" != "true" && "$PUSH_DAILY_REPORT" != "yes" && "$PUSH_DAILY_REPORT" != "on" ]]; then
    return 0
  fi
  python3 - "$ROOT_DIR" "$REPORT_FILE" "$PLATFORM" "$TODAY" "$RUN_DIR" "$COUNT" "$MAX_ROUNDS" "$MAX_EXTRA_ROUNDS" "$MAX_TOTAL_REQUESTS" "$ACCOUNT_POOL" "$ACCOUNT_SUCCESS_TARGET" "$MIN_GOAL_SUCCESS_RATIO" "$TOTAL_SUCCESS_GOAL" "$MIN_TOTAL_SUCCESS" <<'PY'
import sys
from pathlib import Path
import math
import json
from collections import Counter

sys.path.insert(0, "backend")
import flywheel_cli as f
from flywheel.feishu_cards import build_daily_loop_feishu_card
from flywheel.daily_loop_targets import get_pool_target_status

root_dir = Path(sys.argv[1])
report_file = Path(sys.argv[2])
platform = sys.argv[3]
report_day = sys.argv[4]
run_dir = Path(sys.argv[5])
configured_count = int(sys.argv[6])
max_rounds = int(sys.argv[7])
max_extra_rounds = int(sys.argv[8])
max_total_requests = int(sys.argv[9])
account_pool = sys.argv[10]
account_target = int(sys.argv[11])
minimum_ratio = float(sys.argv[12])
configured_target_total = int(sys.argv[13])
configured_min_total = int(sys.argv[14])
if not report_file.exists():
    raise SystemExit(0)

content = report_file.read_text(encoding="utf-8").strip()
if not content:
    raise SystemExit(0)

round_rows = []
for path in sorted(run_dir.glob("*.summary")):
    data = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        data[key] = value
    if data.get("status") in {"done", "blocked", "error"}:
        round_rows.append(
            {
                "round": data.get("round") or "",
                "label": data.get("label") or data.get("round") or "-",
                "status": data.get("status") or "-",
                "status_label": data.get("status_label") or data.get("status") or "-",
                "scheduled_time": data.get("scheduled_time") or "-",
                "started_at": data.get("started_at") or "-",
                "requested_count": int(data.get("requested_count") or 0),
                "success_count": int(data.get("success_count") or 0),
                "failed_count": int(data.get("failed_count") or 0),
                "unsubmitted_count": int(data.get("unsubmitted_count") or 0),
                "note": data.get("note") or "",
            }
        )

total_requested = sum(int(item.get("requested_count") or 0) for item in round_rows)
total_success = sum(int(item.get("success_count") or 0) for item in round_rows)
total_failed = sum(int(item.get("failed_count") or 0) for item in round_rows)
total_unsubmitted = sum(int(item.get("unsubmitted_count") or 0) for item in round_rows)

def load_round_payload(round_name: str) -> dict:
    json_path = run_dir / f"{round_name}.json"
    if not json_path.exists():
        return {}
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}

def normalize_reason(value: object) -> str:
    text = str(value or "").strip()
    return text or "未分类"

failure_reason_counter: Counter[str] = Counter()
safety_reason_counter: Counter[str] = Counter()
failed_accounts: list[str] = []
abnormal_rounds: list[str] = []
safety_rejected_total = 0
for row in round_rows:
    if str(row.get("status") or "").strip() == "error":
        abnormal_rounds.append(
            f"{row.get('label') or '-'}：{row.get('note') or '异常结束'}"
            f"（请求 {int(row.get('requested_count') or 0)} 条，未提交 {int(row.get('unsubmitted_count') or 0)} 条）"
        )
    payload = load_round_payload(str(row.get("round") or ""))
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    failed_tasks = report.get("发布失败任务") if isinstance(report.get("发布失败任务"), list) else []
    for item in failed_tasks:
        if not isinstance(item, dict):
            continue
        failure_reason_counter[normalize_reason(item.get("失败原因") or item.get("错误"))] += 1
        account = str(item.get("账号") or "").strip()
        if account and account not in {"-", ""} and account not in failed_accounts:
            failed_accounts.append(account)
    safety_gate = report.get("安全门槛") if isinstance(report.get("安全门槛"), dict) else {}
    rejected_items = safety_gate.get("拦截明细") if isinstance(safety_gate.get("拦截明细"), list) else []
    if not rejected_items:
        rejected_items = safety_gate.get("拦截预览") if isinstance(safety_gate.get("拦截预览"), list) else []
    for item in rejected_items:
        if not isinstance(item, dict):
            continue
        safety_rejected_total += 1
        safety_reason_counter[normalize_reason(item.get("失败原因") or item.get("原因") or item.get("错误") or item.get("名称"))] += 1

def top_counter_text(counter: Counter[str], *, limit: int = 3) -> str:
    return "、".join(f"{reason} {count} 次" for reason, count in counter.most_common(limit) if count > 0)

failure_summary: list[str] = []
if total_failed > 0 or failure_reason_counter:
    line = f"发布失败共 {total_failed} 条"
    if failed_accounts:
        line += f"，涉及失败账号 {len(failed_accounts)} 个"
    reason_text = top_counter_text(failure_reason_counter)
    if reason_text:
        line += f"；主要原因：{reason_text}"
    line += "。"
    failure_summary.append(line)
if safety_rejected_total > 0 or safety_reason_counter:
    line = f"安全门槛拦截共 {safety_rejected_total} 条"
    reason_text = top_counter_text(safety_reason_counter)
    if reason_text:
        line += f"；主要原因：{reason_text}"
    line += "。"
    failure_summary.append(line)
if abnormal_rounds:
    failure_summary.append("异常轮次：" + "；".join(abnormal_rounds[:5]) + "。")
target_status = get_pool_target_status(
    root_dir=root_dir,
    run_dir=run_dir,
    pool_name=account_pool,
    platform=platform,
    account_success_target=account_target,
)
target_total = int(target_status.get("target_total_success") or 0)
if configured_target_total > 0:
    target_total = configured_target_total
eligible_accounts = int(target_status.get("eligible_pool_size") or 0)
count = configured_count if configured_count > 0 else max(eligible_accounts, 1)
count = min(count, max(eligible_accounts, 1))
remaining_deficit = int(target_status.get("remaining_success_deficit") or 0)
unmet_account_count = int(target_status.get("unmet_account_count") or 0)
min_account_success = int(target_status.get("min_success_count") or 0)
minimum_success = int(math.ceil(target_total * minimum_ratio)) if target_total > 0 else 0
if configured_min_total > 0:
    minimum_success = configured_min_total
remaining_deficit = max(minimum_success - total_success, 0)
effective_extra_rounds = max_extra_rounds if max_extra_rounds > 0 else "按缺口持续补量"
minimum_budget = int(math.ceil(minimum_success * 100 / 35)) if minimum_success > 0 else 0
if minimum_budget > 0 and count > 0:
    minimum_budget = int(math.ceil(minimum_budget / count) * count)
effective_budget = max(max_total_requests, minimum_budget)

conclusions = []
if remaining_deficit <= 0:
    conclusions.append(f"当前累计成功 {total_success} 条；已达到今日最低成功底线 {minimum_success} 条，今日停止继续发布。")
else:
    conclusions.append(f"当前累计成功 {total_success} 条；距今日最低成功底线 {minimum_success} 条仍差 {remaining_deficit} 条。")
conclusions.append(
    f"当日总目标成功数为 {target_total} 条，最低成功底线为 {minimum_success} 条；当前累计成功 {total_success} 条。"
)
conclusions.append("详细单轮任务明细仍以各次批量发布测试报告为准。")

card_payload = {
    "date": report_day,
    "platform": platform,
    "target_range": f"{account_pool}：{eligible_accounts} 个可用账号，每账号至少成功 {account_target} 条（日总目标成功 {target_total} 条）",
    "executed_rounds": len(round_rows),
    "total_requested": total_requested,
    "total_success": total_success,
    "total_failed": total_failed,
    "total_unsubmitted": total_unsubmitted,
    "strategy_text": f"调度策略：每轮最多请求 {count} 条；前 {max_rounds} 轮按时段执行；按账号成功缺口持续补量，直到每个可用账号达标。",
    "fuse_text": f"保险丝：补量轮上限 {effective_extra_rounds}；单日请求预算 {effective_budget} 条；最低成功底线 {minimum_success} 条。",
    "round_rows": round_rows,
    "conclusions": conclusions,
    "pool_name": account_pool,
    "eligible_accounts": eligible_accounts,
    "account_target": account_target,
    "remaining_deficit": remaining_deficit,
    "unmet_account_count": unmet_account_count,
    "min_account_success": min_account_success,
    "minimum_goal_success": minimum_success,
    "minimum_goal_success_ratio": minimum_ratio,
    "failure_summary": failure_summary,
}

token = f._feishu_get_tenant_access_token()
receive_id_type, receive_id = f._feishu_receive_target()
try:
    result = f._feishu_send_interactive_message(
        token,
        receive_id_type=receive_id_type,
        receive_id=receive_id,
        card=build_daily_loop_feishu_card(card_payload),
    )
except Exception:
    result = f._feishu_send_text_message(
        token,
        receive_id_type=receive_id_type,
        receive_id=receive_id,
        text=(
            f"短剧日常自动发布测试总结（{report_day}）\n"
            f"平台：{platform}\n"
            f"累计成功：{total_success} 条，失败：{total_failed} 条，未提交：{total_unsubmitted} 条。\n"
            "说明：卡片发送失败，已保留本地总结文件。"
        ),
    )
print(str(result.get("message_id") or ""))
PY
}

push_round_notice() {
  local label="$1"
  local started_at="$2"
  local finished_at="$3"
  if [[ "$PUSH_ROUND_NOTICE" != "1" && "$PUSH_ROUND_NOTICE" != "true" && "$PUSH_ROUND_NOTICE" != "yes" && "$PUSH_ROUND_NOTICE" != "on" ]]; then
    return 0
  fi
  ROUND_NOTICE_LABEL="$label" ROUND_NOTICE_STARTED_AT="$started_at" ROUND_NOTICE_FINISHED_AT="$finished_at" python3 -c '
import os, sys
sys.path.insert(0, "backend")
import flywheel_cli as f
label = str(os.getenv("ROUND_NOTICE_LABEL") or "").strip() or "本轮"
started_at = str(os.getenv("ROUND_NOTICE_STARTED_AT") or "").strip() or "-"
finished_at = str(os.getenv("ROUND_NOTICE_FINISHED_AT") or "").strip() or "-"
token = f._feishu_get_tenant_access_token()
receive_id_type, receive_id = f._feishu_receive_target()
message = f"Barry 日常 loop：{label}已结束，开始时间 {started_at}，结束时间 {finished_at}。"
result = f._feishu_send_text_message(
    token,
    receive_id_type=receive_id_type,
    receive_id=receive_id,
    text=message,
)
print(str(result.get("message_id") or ""))
'
}

delete_daily_reports_after_push() {
  if [[ "$DELETE_REPORT_AFTER_PUSH" != "1" && "$DELETE_REPORT_AFTER_PUSH" != "true" && "$DELETE_REPORT_AFTER_PUSH" != "yes" && "$DELETE_REPORT_AFTER_PUSH" != "on" ]]; then
    return 0
  fi
  rm -f "$REPORT_FILE"
  local summary report_file
  for summary in "$RUN_DIR"/*.summary; do
    [[ -f "$summary" ]] || continue
    report_file="$(awk -F= '$1=="report_file"{sub(/^[^=]*=/,""); print; exit}' "$summary" 2>/dev/null || true)"
    if [[ -n "$report_file" && -f "$report_file" ]]; then
      rm -f "$report_file"
    fi
  done
}

line_label_zh() {
  local line_name="$1"
  case "$line_name" in
    realtime)
      echo "实时榜线"
      ;;
    ordinary)
      echo "普通池线"
      ;;
    *)
      echo "$line_name"
      ;;
  esac
}

run_batch_command_to_json() {
  local round_name="$1"
  local round_label="$2"
  local scheduled="$3"
  local started="$4"
  local line_name="$5"
  local pool_name="$6"
  local realtime_enabled="$7"
  local requested_count="$8"
  local json_path="$9"
  local account_json

  account_json="$(select_round_account_ids_for_pool "$pool_name" "$requested_count")"
  local account_ids
  mapfile -t account_ids < <(python3 - "$account_json" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
for item in payload.get("account_ids") or []:
    value = str(item or "").strip()
    if value:
        print(value)
PY
)
  if [[ "${#account_ids[@]}" -lt "$requested_count" ]]; then
    log "${round_label}$(printf '（%s）' "$(line_label_zh "$line_name")") 账号池可用账号不足，需 ${requested_count} 个，当前 ${#account_ids[@]} 个。"
    return 1
  fi

  local line_report_dir="$RUN_DIR/line-test-summary/$round_name/$line_name"
  local cmd=(
    env
    BARRY_FEISHU_TEST_PUSH=0
    BARRY_VIDEO_TEST_SUMMARY_DIR="$line_report_dir"
    BARRY_LOOP_LINE_NAME="$line_name"
    BARRY_LOOP_ROUND_LABEL="${round_label}（$(line_label_zh "$line_name")）"
    BARRY_LOOP_ROUND_SCHEDULED_TIME="$scheduled"
    BARRY_LOOP_ROUND_STARTED_AT="$started"
    BARRY_REALTIME_RANK_ENABLED="$realtime_enabled"
    python3 backend/flywheel_cli.py run-batch-drama
    --execute
    --count "$requested_count"
    --publish-platform "$PLATFORM"
    --json
  )
  for account_id in "${account_ids[@]}"; do
    cmd+=(--account-id "$account_id")
  done
  if is_truthy "$ALLOW_ACCOUNT_REUSE"; then
    cmd+=(--allow-account-reuse)
  fi

  if "${cmd[@]}" >"$json_path" 2>>"$LOG_FILE"; then
    return 0
  fi
  log "${round_label}$(printf '（%s）' "$(line_label_zh "$line_name")") 命令执行返回非零状态，继续按结果文件尝试汇总。"
  return 1
}

merge_round_line_payloads() {
  local requested_count="$1"
  local line_meta_tsv="$2"
  local json_path="$3"
  BARRY_FEISHU_TEST_PUSH=0 BARRY_VIDEO_TEST_SUMMARY_DIR="$REPORT_DIR" python3 - "$ROOT_DIR" "$requested_count" "$PLATFORM" "$line_meta_tsv" "$json_path" <<'PY'
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

root_dir = Path(sys.argv[1]).resolve()
requested_count = int(sys.argv[2] or 0)
platform = sys.argv[3]
line_meta_tsv = Path(sys.argv[4]).resolve()
json_path = Path(sys.argv[5]).resolve()

sys.path.insert(0, str(root_dir / "backend"))
import flywheel_cli as f


def load_payload(path_str: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


line_rows = []
with line_meta_tsv.open("r", encoding="utf-8") as handle:
    reader = csv.DictReader(handle, delimiter="\t")
    for row in reader:
        if row:
            line_rows.append(dict(row))

all_items: list[dict] = []
all_records: list[dict] = []
all_skipped_preview: list[dict] = []
all_platform_plan: list[object] = []
all_cleanup_deleted: list[str] = []
all_cleanup_errors: list[str] = []
episode_precheck: dict[str, object] = {"lines": {}}
strategy_memory: dict[str, object] = {"lines": {}}
safety_gate_totals: dict[str, int] = defaultdict(int)
safety_gate_preview: list[dict] = []
safety_gate_details: list[dict] = []
timings: dict[str, float] = defaultdict(float)
line_runs: list[dict[str, object]] = []
unique_playable_source_count = 0
realtime_external_unique_count = 0
realtime_external_slot_fill_count = 0
source_reuse_fill_count = 0
planned_shortfall_count = max(requested_count, 0)
merged_status = "done"
messages: list[str] = []
next_index = 1

for row in line_rows:
    line_name = str(row.get("line_name") or "").strip()
    pool_name = str(row.get("pool_name") or "").strip()
    realtime_enabled = str(row.get("realtime_enabled") or "").strip()
    line_requested = int(row.get("requested_count") or 0)
    eligible_pool_size = int(row.get("eligible_pool_size") or 0)
    payload = load_payload(str(row.get("json_path") or ""))
    payload_status = str(payload.get("status") or "").strip()
    payload_message = str(payload.get("message") or payload.get("error") or "").strip()
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    records = payload.get("publish_records") if isinstance(payload.get("publish_records"), list) else []
    line_success = 0
    line_failed = 0
    line_other = 0
    for item in items:
        copied = dict(item)
        copied["index"] = next_index
        copied["line_name"] = line_name
        next_index += 1
        all_items.append(copied)
        status = str(copied.get("status") or "").strip()
        if status == "published_submitted":
            line_success += 1
        elif status == "failed":
            line_failed += 1
        else:
            line_other += 1
    all_records.extend(records)
    all_skipped_preview.extend(payload.get("skipped_preview") if isinstance(payload.get("skipped_preview"), list) else [])
    all_platform_plan.extend(payload.get("drama_platform_plan") if isinstance(payload.get("drama_platform_plan"), list) else [])
    cleanup = payload.get("cleanup") if isinstance(payload.get("cleanup"), dict) else {}
    all_cleanup_deleted.extend([str(path) for path in (cleanup.get("deleted_paths") or []) if str(path).strip()])
    all_cleanup_errors.extend([str(err) for err in (cleanup.get("errors") or []) if str(err).strip()])
    line_episode_precheck = payload.get("episode_precheck") if isinstance(payload.get("episode_precheck"), dict) else {}
    if line_episode_precheck:
        episode_precheck["lines"][line_name] = line_episode_precheck
    line_strategy_memory = payload.get("strategy_memory") if isinstance(payload.get("strategy_memory"), dict) else {}
    if line_strategy_memory:
        strategy_memory["lines"][line_name] = line_strategy_memory
    safety_gate = payload.get("safety_gate") if isinstance(payload.get("safety_gate"), dict) else {}
    for key in (
        "passed_count",
        "rejected_count",
        "replacement_filled_count",
        "reserve_source_count",
        "reserve_attempt_count",
        "unfilled_count",
    ):
        safety_gate_totals[key] += int(safety_gate.get(key) or 0)
    safety_gate_preview.extend(list(safety_gate.get("rejected_preview") or []))
    safety_gate_details.extend(list(safety_gate.get("rejected_details") or []))
    for key, value in (payload.get("timings") if isinstance(payload.get("timings"), dict) else {}).items():
        try:
            timings[str(key)] += float(value or 0.0)
        except Exception:
            continue
    unique_playable_source_count += int(payload.get("unique_playable_source_count") or 0)
    realtime_external_unique_count += int(payload.get("realtime_external_unique_count") or 0)
    realtime_external_slot_fill_count += int(payload.get("realtime_external_slot_fill_count") or 0)
    source_reuse_fill_count += int(payload.get("source_reuse_fill_count") or 0)
    planned_shortfall_count -= len(items)
    line_runs.append(
        {
            "线路": "实时榜线" if line_name == "realtime" else ("普通池线" if line_name == "ordinary" else line_name),
            "line_name": line_name,
            "账号池": pool_name,
            "请求数": line_requested,
            "成功数": line_success,
            "失败数": line_failed,
            "其他状态数": line_other,
            "可用账号数": eligible_pool_size,
            "实时榜开关": "开启" if realtime_enabled in {"1", "true", "yes", "on"} else "关闭",
        }
    )
    if payload_message:
        messages.append(f"{line_name}: {payload_message}")
    if payload_status and payload_status not in {"done", "success", "ok", "dry_run"}:
        merged_status = payload_status if merged_status == "done" else merged_status

planned_shortfall_count = max(planned_shortfall_count, 0)
payload = {
    "status": "done" if all_items or line_runs else (merged_status or "error"),
    "mode": "batch_drama",
    "platform": platform,
    "requested_count": requested_count,
    "items": all_items,
    "publish_records": all_records,
    "drama_platform_plan": all_platform_plan,
    "episode_precheck": episode_precheck,
    "safety_gate": {
        **safety_gate_totals,
        "rejected_preview": safety_gate_preview[:10],
        "rejected_details": safety_gate_details,
    },
    "strategy_memory": strategy_memory,
    "skipped_preview": all_skipped_preview[:20],
    "unique_playable_source_count": unique_playable_source_count,
    "source_reuse_fill_count": source_reuse_fill_count,
    "realtime_external_unique_count": realtime_external_unique_count,
    "realtime_external_slot_fill_count": realtime_external_slot_fill_count,
    "planned_shortfall_count": planned_shortfall_count,
    "cleanup": {
        "enabled": True,
        "deleted_paths": all_cleanup_deleted,
        "errors": all_cleanup_errors,
    },
    "timings": dict(timings),
    "timing_zh": f._format_timing_zh(dict(timings)),
    "line_runs": line_runs,
}
if messages:
    payload["message"] = "；".join(messages[:10])
payload["report_zh"] = f._batch_report_zh(payload)
payload["report_zh"]["线路汇总"] = line_runs
payload["user_summary_zh"] = f._batch_user_summary_zh(payload["report_zh"])
payload["retry_prompt_zh"] = f._failed_publish_prompt_zh(payload["report_zh"])
payload = f._finalize_payload(payload)
json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

run_round() {
  local round="$1"
  local requested_count="$2"
  local label scheduled started json_path summary_path account_json
  label="$(round_label "$round")"
  scheduled="$(round_scheduled_datetime "$round")"
  started="$(date '+%F %T')"
  json_path="$RUN_DIR/$round.json"
  summary_path="$(round_summary_path "$round")"

  if is_truthy "$SPLIT_SHORT_DRAMA_LINES"; then
    local line_plan_json line_meta_tsv line_json_dir
    line_plan_json="$(split_round_line_plan "$requested_count")"
    line_meta_tsv="$RUN_DIR/$round.lines.tsv"
    line_json_dir="$RUN_DIR/$round.lines"
    mkdir -p "$line_json_dir"
    cat >"$line_meta_tsv" <<'EOF'
line_name	pool_name	requested_count	realtime_rank_enabled	eligible_pool_size	json_path
EOF

    local total_line_requested=0
    while IFS=$'\t' read -r line_name pool_name line_requested realtime_enabled eligible_pool_size; do
      [[ -n "$line_name" ]] || continue
      [[ "$line_requested" =~ ^[0-9]+$ ]] || line_requested=0
      if (( line_requested <= 0 )); then
        log "${label}（$(line_label_zh "$line_name")）跳过：线路无可用请求槽位，账号池=${pool_name}，可用账号=${eligible_pool_size:-0}。"
        continue
      fi
      local line_json_path="$line_json_dir/$line_name.json"
      total_line_requested=$((total_line_requested + line_requested))
      log "${label}（$(line_label_zh "$line_name")）开始执行，目标平台=${PLATFORM}，计划数量=${line_requested}，账号池=${pool_name}，实时榜=$( [[ "$realtime_enabled" == "1" || "$realtime_enabled" == "true" ]] && echo 开启 || echo 关闭 )。"
      run_batch_command_to_json "$round" "$label" "$scheduled" "$started" "$line_name" "$pool_name" "$realtime_enabled" "$line_requested" "$line_json_path" || true
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$line_name" "$pool_name" "$line_requested" "$realtime_enabled" "${eligible_pool_size:-0}" "$line_json_path" >>"$line_meta_tsv"
    done < <(python3 - "$line_plan_json" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
for item in payload.get("lines") or []:
    if not isinstance(item, dict):
        continue
    print(
        "\t".join(
            [
                str(item.get("line_name") or "").strip(),
                str(item.get("pool_name") or "").strip(),
                str(int(item.get("requested_count") or 0)),
                "1" if item.get("realtime_rank_enabled") else "0",
                str(int(item.get("eligible_pool_size") or 0)),
            ]
        )
    )
PY
    )
    if (( total_line_requested <= 0 )); then
      log "${label} 双线路均无可执行账号槽位，跳过本轮。"
      return 1
    fi
    if (( total_line_requested < requested_count )); then
      log "${label} 双线路可执行总槽位不足，请求 ${requested_count} 条，实际仅能执行 ${total_line_requested} 条；缺口将写入本轮报告。"
    fi
    merge_round_line_payloads "$requested_count" "$line_meta_tsv" "$json_path"
  else
    account_json="$(select_round_account_ids "$requested_count")"
    local account_ids
    mapfile -t account_ids < <(python3 - "$account_json" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
for item in payload.get("account_ids") or []:
    value = str(item or "").strip()
    if value:
        print(value)
PY
)
    if [[ "${#account_ids[@]}" -lt "$requested_count" ]]; then
      log "${label} 账号池可用账号不足，需 ${requested_count} 个，当前 ${#account_ids[@]} 个。"
      return 1
    fi

    log "${label} 开始执行，目标平台=${PLATFORM}，计划数量=${requested_count}，账号池=${ACCOUNT_POOL}。"

    local cmd=(
      env
      BARRY_FEISHU_TEST_PUSH=0
      BARRY_LOOP_ROUND_LABEL="$label"
      BARRY_LOOP_ROUND_SCHEDULED_TIME="$scheduled"
      BARRY_LOOP_ROUND_STARTED_AT="$started"
      python3 backend/flywheel_cli.py run-batch-drama
      --execute
      --count "$requested_count"
      --publish-platform "$PLATFORM"
      --json
    )
    for account_id in "${account_ids[@]}"; do
      cmd+=(--account-id "$account_id")
    done
    if [[ "$ALLOW_ACCOUNT_REUSE" == "1" ]]; then
      cmd+=(--allow-account-reuse)
    fi

    if "${cmd[@]}" >"$json_path" 2>>"$LOG_FILE"; then
      :
    else
      log "$label 命令执行返回非零状态，继续按结果文件尝试汇总。"
    fi
  fi

  python3 - "$json_path" "$summary_path" "$round" "$label" "$scheduled" "$started" "$requested_count" <<'PY'
import json
import sys
from pathlib import Path

json_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
round_name = sys.argv[3]
label = sys.argv[4]
scheduled = sys.argv[5]
started = sys.argv[6]
requested_arg = int(sys.argv[7] or 0)

payload = {}
try:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
except Exception:
    payload = {}

report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
payload_status = str(payload.get("status") or "").strip()
payload_message = str(payload.get("message") or payload.get("error") or "").strip()
requested = int(payload.get("requested_count") or report.get("请求数量") or requested_arg or 0)
success = int(report.get("发布成功数") or 0)
failed = int(report.get("失败数") or 0)
processing = int(report.get("发布处理中数") or 0)
planned = int(report.get("计划数量") or requested or requested_arg or 0)
unsubmitted = max(planned - success - failed - processing, 0)
status = "done" if payload else "error"
status_label = "已完成"
note = ""
if payload_status and payload_status not in {"success", "ok", "done"}:
    if payload_status == "no_enough_playable_dramas":
        status = "blocked"
        status_label = "素材不足"
        requested = max(requested, requested_arg)
        planned = max(planned, requested_arg)
        unsubmitted = max(unsubmitted, requested_arg)
    else:
        status = "error"
        status_label = "异常结束"
    note = payload_message or payload_status
elif not payload:
    status_label = "异常结束"
    note = "结果文件为空或不可解析"

report_files = payload.get("test_report_files") if isinstance(payload.get("test_report_files"), dict) else {}
report_file = str(report_files.get("markdown") or "")

lines = [
    f"round={round_name}",
    f"label={label}",
    f"scheduled_time={scheduled}",
    f"started_at={started}",
    f"status={status}",
    f"status_label={status_label}",
    f"requested_count={requested}",
    f"planned_count={planned}",
    f"success_count={success}",
    f"failed_count={failed}",
    f"processing_count={processing}",
    f"unsubmitted_count={unsubmitted}",
    f"report_file={report_file}",
    f"note={note}",
]
summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

  write_daily_report
  local finished_at
  finished_at="$(date '+%F %T')"
  if message_id="$(push_round_notice "$label" "$started" "$finished_at" 2>>"$LOG_FILE")"; then
    if [[ -n "$message_id" ]]; then
      log "$label 结束通知已发送到飞书，message_id=${message_id}。"
    fi
  else
    log "$label 结束通知发送失败，详情见日志。"
  fi
  log "$label 执行完成。"
}

log_request_decision() {
  local label="$1"
  local requested_count="$2"
  local total_success total_requested budget_text budget_cap minimum_success
  local remaining_deficit unmet_account_count
  total_success="$(sum_success)"
  total_requested="$(sum_requested)"
  remaining_deficit="$(effective_remaining_success_deficit)"
  unmet_account_count="$(account_target_field unmet_account_count)"
  budget_cap="$(effective_max_total_requests)"
  minimum_success="$(minimum_goal_success)"
  if (( budget_cap > 0 )); then
    budget_text="累计请求=${total_requested}/${budget_cap}"
  else
    budget_text="累计请求=${total_requested}"
  fi
  log "${label} 调度决策：账号池每账号目标=${ACCOUNT_SUCCESS_TARGET} 条，日总目标=$(effective_target_total_success) 条，最低成功底线=${minimum_success} 条，当前累计成功=${total_success}，未达标账号=${unmet_account_count} 个，剩余缺口=${remaining_deficit} 条，${budget_text}，本轮请求=${requested_count}。"
}

wait_until_round_time() {
  local round="$1"
  local target_epoch now_epoch
  target_epoch="$(round_target_epoch "$round")"
  while true; do
    now_epoch="$(date +%s)"
    if (( now_epoch >= target_epoch )); then
      return 0
    fi
    sleep 30
  done
}

maybe_run_round() {
  local round="$1"
  local requested_count round_no remaining_deficit
  round_no="${round#round}"
  if (( round_no > MAX_ROUNDS )); then
    return 0
  fi
  if round_done "$round"; then
    return 0
  fi
  wait_until_round_time "$round"
  remaining_deficit="$(effective_remaining_success_deficit)"
  if [[ ! "$remaining_deficit" =~ ^[0-9]+$ ]]; then
    remaining_deficit=0
  fi
  if (( remaining_deficit <= 0 )); then
    cat >"$(round_summary_path "$round")" <<EOF
round=$round
label=$(round_label "$round")
scheduled_time=$(round_scheduled_datetime "$round")
started_at=
status=skipped
requested_count=0
planned_count=0
success_count=0
failed_count=0
processing_count=0
unsubmitted_count=0
report_file=
EOF
    write_daily_report
      log "$(round_label "$round")跳过，已达到今日最低成功底线。"
    return 0
  fi
  requested_count="$(next_round_request_count "$round")"
  if (( requested_count <= 0 )); then
    log "$(round_label "$round")跳过，当前无需继续追加请求。"
    return 0
  fi
  log_request_decision "$(round_label "$round")" "$requested_count"
  run_round "$round" "$requested_count"
}

run_extra_rounds_if_needed() {
  local extra_index=1 total_requested requested_count round_name remaining_deficit budget_cap
  while true; do
    if (( MAX_EXTRA_ROUNDS > 0 && extra_index > MAX_EXTRA_ROUNDS )); then
      break
    fi
    remaining_deficit="$(effective_remaining_success_deficit)"
    if [[ ! "$remaining_deficit" =~ ^[0-9]+$ ]]; then
      remaining_deficit=0
    fi
    if (( remaining_deficit <= 0 )); then
      return 0
    fi
    total_requested="$(sum_requested)"
    budget_cap="$(effective_max_total_requests)"
    if (( budget_cap > 0 && total_requested >= budget_cap )); then
      log "补量停止：累计请求 ${total_requested} 条，已达到单日请求预算上限 ${budget_cap} 条。"
      return 0
    fi
    requested_count="$(next_round_request_count "round${MAX_ROUNDS}")"
    if (( requested_count <= 0 )); then
      return 0
    fi
    round_name="extra${extra_index}"
    log_request_decision "$(round_label "$round_name")" "$requested_count"
    run_round "$round_name" "$requested_count"
    extra_index=$((extra_index + 1))
  done
  remaining_deficit="$(account_target_field remaining_success_deficit)"
  if [[ "$remaining_deficit" =~ ^[0-9]+$ ]] && (( remaining_deficit > 0 )); then
    log "补量轮达到上限 ${MAX_EXTRA_ROUNDS} 轮后仍有 ${remaining_deficit} 条账号成功缺口未补齐。"
  fi
}

log "日常调度器启动。平台=${PLATFORM}，每轮请求上限=$(resolved_round_request_cap)，基础轮=${MAX_ROUNDS}，补量轮上限=${MAX_EXTRA_ROUNDS}，账号池=${ACCOUNT_POOL}，每个可用账号目标=${ACCOUNT_SUCCESS_TARGET} 条，日总目标=$(effective_target_total_success) 条，最低成功底线=$(minimum_goal_success) 条，轮次时间=${ROUND_TIMES_CSV}，单日请求预算=$(effective_max_total_requests) 条。"

for ((round_index=1; round_index<=MAX_ROUNDS; round_index++)); do
  maybe_run_round "round${round_index}"
done
run_extra_rounds_if_needed

write_daily_report
