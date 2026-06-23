#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PLATFORM="${STEVEN_LOOP_PLATFORM:-${BARRY_LOOP_PLATFORM:-FACEBOOK}}"
COUNT="${STEVEN_LOOP_COUNT:-${BARRY_LOOP_COUNT:-20}}"
MIN_SUCCESS_TARGET="${STEVEN_LOOP_MIN_SUCCESS_TARGET:-${BARRY_LOOP_MIN_SUCCESS_TARGET:-100}}"
MAX_ROUNDS="${STEVEN_LOOP_MAX_ROUNDS:-${BARRY_LOOP_MAX_ROUNDS:-10}}"
ROUND1_AT="${STEVEN_LOOP_ROUND1_AT:-${BARRY_LOOP_ROUND1_AT:-10:00}}"
ROUND2_AT="${STEVEN_LOOP_ROUND2_AT:-${BARRY_LOOP_ROUND2_AT:-11:30}}"
ROUND3_AT="${STEVEN_LOOP_ROUND3_AT:-${BARRY_LOOP_ROUND3_AT:-13:30}}"
ROUND4_AT="${STEVEN_LOOP_ROUND4_AT:-${BARRY_LOOP_ROUND4_AT:-15:00}}"
ROUND5_AT="${STEVEN_LOOP_ROUND5_AT:-${BARRY_LOOP_ROUND5_AT:-16:30}}"
ROUND6_AT="${STEVEN_LOOP_ROUND6_AT:-${BARRY_LOOP_ROUND6_AT:-18:00}}"
ROUND7_AT="${STEVEN_LOOP_ROUND7_AT:-${BARRY_LOOP_ROUND7_AT:-19:30}}"
ROUND8_AT="${STEVEN_LOOP_ROUND8_AT:-${BARRY_LOOP_ROUND8_AT:-21:00}}"
ROUND9_AT="${STEVEN_LOOP_ROUND9_AT:-${BARRY_LOOP_ROUND9_AT:-22:00}}"
ROUND10_AT="${STEVEN_LOOP_ROUND10_AT:-${BARRY_LOOP_ROUND10_AT:-23:00}}"
PUBLISH_SCHEDULE_ENABLED="${STEVEN_LOOP_PUBLISH_SCHEDULE_ENABLED:-${BARRY_LOOP_PUBLISH_SCHEDULE_ENABLED:-1}}"
PUBLISH_WINDOW_START="${STEVEN_LOOP_PUBLISH_WINDOW_START:-${BARRY_LOOP_PUBLISH_WINDOW_START:-18:00}}"
PUBLISH_WINDOW_END="${STEVEN_LOOP_PUBLISH_WINDOW_END:-${BARRY_LOOP_PUBLISH_WINDOW_END:-12:00}}"
PUBLISH_TIMEZONE="${STEVEN_LOOP_PUBLISH_TIMEZONE:-${BARRY_LOOP_PUBLISH_TIMEZONE:-Asia/Shanghai}}"
PUBLISH_LEAD_MINUTES="${STEVEN_LOOP_PUBLISH_LEAD_MINUTES:-${BARRY_LOOP_PUBLISH_LEAD_MINUTES:-5}}"
COLLECT_WAIT_SECONDS="${STEVEN_LOOP_COLLECT_WAIT_SECONDS:-${BARRY_LOOP_COLLECT_WAIT_SECONDS:-60}}"
COLLECT_POLL_INTERVAL="${STEVEN_LOOP_COLLECT_POLL_INTERVAL:-${BARRY_LOOP_COLLECT_POLL_INTERVAL:-10}}"
TEAM_LANGUAGE_FILE="${STEVEN_LOOP_TEAM_LANGUAGE_FILE:-${BARRY_LOOP_TEAM_LANGUAGE_FILE:-}}"
ROUND1_KIND="${STEVEN_LOOP_ROUND1_KIND:-${BARRY_LOOP_ROUND1_KIND:-vidu_growth_startend}}"
ROUND2_KIND="${STEVEN_LOOP_ROUND2_KIND:-${BARRY_LOOP_ROUND2_KIND:-vidu_growth_img2video}}"
ROUND3_KIND="${STEVEN_LOOP_ROUND3_KIND:-${BARRY_LOOP_ROUND3_KIND:-batch_drama}}"
ROUND4_KIND="${STEVEN_LOOP_ROUND4_KIND:-${BARRY_LOOP_ROUND4_KIND:-batch_drama}}"
ROUND5_KIND="${STEVEN_LOOP_ROUND5_KIND:-${BARRY_LOOP_ROUND5_KIND:-batch_drama}}"
ROUND6_KIND="${STEVEN_LOOP_ROUND6_KIND:-${BARRY_LOOP_ROUND6_KIND:-batch_drama}}"
ROUND7_KIND="${STEVEN_LOOP_ROUND7_KIND:-${BARRY_LOOP_ROUND7_KIND:-batch_drama}}"
ROUND8_KIND="${STEVEN_LOOP_ROUND8_KIND:-${BARRY_LOOP_ROUND8_KIND:-batch_drama}}"
ROUND9_KIND="${STEVEN_LOOP_ROUND9_KIND:-${BARRY_LOOP_ROUND9_KIND:-batch_drama}}"
ROUND10_KIND="${STEVEN_LOOP_ROUND10_KIND:-${BARRY_LOOP_ROUND10_KIND:-batch_drama}}"
DEFAULT_CLIP_ENGINE="${STEVEN_LOOP_CLIP_ENGINE:-${BARRY_LOOP_CLIP_ENGINE:-ai_animation}}"
CANDIDATE_SOURCE="${STEVEN_LOOP_CANDIDATE_SOURCE:-${BARRY_LOOP_CANDIDATE_SOURCE:-h5_new}}"
ROUND1_CLIP_ENGINE="${STEVEN_LOOP_ROUND1_CLIP_ENGINE:-${BARRY_LOOP_ROUND1_CLIP_ENGINE:-$DEFAULT_CLIP_ENGINE}}"
ROUND2_CLIP_ENGINE="${STEVEN_LOOP_ROUND2_CLIP_ENGINE:-${BARRY_LOOP_ROUND2_CLIP_ENGINE:-$DEFAULT_CLIP_ENGINE}}"
ROUND3_CLIP_ENGINE="${STEVEN_LOOP_ROUND3_CLIP_ENGINE:-${BARRY_LOOP_ROUND3_CLIP_ENGINE:-$DEFAULT_CLIP_ENGINE}}"
ROUND4_CLIP_ENGINE="${STEVEN_LOOP_ROUND4_CLIP_ENGINE:-${BARRY_LOOP_ROUND4_CLIP_ENGINE:-$DEFAULT_CLIP_ENGINE}}"
ROUND5_CLIP_ENGINE="${STEVEN_LOOP_ROUND5_CLIP_ENGINE:-${BARRY_LOOP_ROUND5_CLIP_ENGINE:-$DEFAULT_CLIP_ENGINE}}"
ROUND6_CLIP_ENGINE="${STEVEN_LOOP_ROUND6_CLIP_ENGINE:-${BARRY_LOOP_ROUND6_CLIP_ENGINE:-$DEFAULT_CLIP_ENGINE}}"
ROUND7_CLIP_ENGINE="${STEVEN_LOOP_ROUND7_CLIP_ENGINE:-${BARRY_LOOP_ROUND7_CLIP_ENGINE:-$DEFAULT_CLIP_ENGINE}}"
ROUND8_CLIP_ENGINE="${STEVEN_LOOP_ROUND8_CLIP_ENGINE:-${BARRY_LOOP_ROUND8_CLIP_ENGINE:-$DEFAULT_CLIP_ENGINE}}"
ROUND9_CLIP_ENGINE="${STEVEN_LOOP_ROUND9_CLIP_ENGINE:-${BARRY_LOOP_ROUND9_CLIP_ENGINE:-$DEFAULT_CLIP_ENGINE}}"
ROUND10_CLIP_ENGINE="${STEVEN_LOOP_ROUND10_CLIP_ENGINE:-${BARRY_LOOP_ROUND10_CLIP_ENGINE:-$DEFAULT_CLIP_ENGINE}}"
REPORT_DIR="${STEVEN_LOOP_REPORT_DIR:-${BARRY_LOOP_REPORT_DIR:-$ROOT_DIR/runtime/reports/test-summary}}"
STATE_ROOT="${STEVEN_LOOP_STATE_ROOT:-${BARRY_LOOP_STATE_ROOT:-$ROOT_DIR/data/daily-loop}}"
ALLOW_ACCOUNT_REUSE="${STEVEN_LOOP_ALLOW_ACCOUNT_REUSE:-${BARRY_LOOP_ALLOW_ACCOUNT_REUSE:-0}}"
TEAM_IDS_FILE="${STEVEN_LOOP_TEAM_IDS_FILE:-${BARRY_LOOP_TEAM_IDS_FILE:-}}"
TEAM_IDS="${STEVEN_LOOP_TEAM_IDS:-${BARRY_LOOP_TEAM_IDS:-}}"
AB_ENABLED="${STEVEN_LOOP_AB_ENABLED:-${BARRY_LOOP_AB_ENABLED:-0}}"
AB_GROUP_A_TEAM_IDS_FILE="${STEVEN_LOOP_AB_GROUP_A_TEAM_IDS_FILE:-${BARRY_LOOP_AB_GROUP_A_TEAM_IDS_FILE:-}}"
AB_GROUP_B_TEAM_IDS_FILE="${STEVEN_LOOP_AB_GROUP_B_TEAM_IDS_FILE:-${BARRY_LOOP_AB_GROUP_B_TEAM_IDS_FILE:-}}"
AB_GROUP_A_CLIP_ENGINE="${STEVEN_LOOP_AB_GROUP_A_CLIP_ENGINE:-${BARRY_LOOP_AB_GROUP_A_CLIP_ENGINE:-legacy}}"
AB_GROUP_B_CLIP_ENGINE="${STEVEN_LOOP_AB_GROUP_B_CLIP_ENGINE:-${BARRY_LOOP_AB_GROUP_B_CLIP_ENGINE:-ai_animation}}"
AB_GROUP_A_LABEL="${STEVEN_LOOP_AB_GROUP_A_LABEL:-${BARRY_LOOP_AB_GROUP_A_LABEL:-A-legacy-beidou}}"
AB_GROUP_B_LABEL="${STEVEN_LOOP_AB_GROUP_B_LABEL:-${BARRY_LOOP_AB_GROUP_B_LABEL:-B-current-ai-cut}}"
VIDU_GROWTH_SCRIPT="${STEVEN_LOOP_VIDU_GROWTH_SCRIPT:-${BARRY_LOOP_VIDU_GROWTH_SCRIPT:-$HOME/.codex/skills/beidou-novel-ops/scripts/vidu_growth_ab_round.js}}"
VIDU_GROWTH_TEAM_IDS_FILE="${STEVEN_LOOP_VIDU_GROWTH_TEAM_IDS_FILE:-${BARRY_LOOP_VIDU_GROWTH_TEAM_IDS_FILE:-$HOME/.barry-video/account-splits/fb-novel-team-ids.txt}}"
VIDU_GROWTH_VARIANTS="${STEVEN_LOOP_VIDU_GROWTH_VARIANTS:-${BARRY_LOOP_VIDU_GROWTH_VARIANTS:-4}}"
VIDU_GROWTH_DURATION="${STEVEN_LOOP_VIDU_GROWTH_DURATION:-${BARRY_LOOP_VIDU_GROWTH_DURATION:-4}}"
VIDU_GROWTH_RESOLUTION="${STEVEN_LOOP_VIDU_GROWTH_RESOLUTION:-${BARRY_LOOP_VIDU_GROWTH_RESOLUTION:-360p}}"
VIDU_GROWTH_MODEL="${STEVEN_LOOP_VIDU_GROWTH_MODEL:-${BARRY_LOOP_VIDU_GROWTH_MODEL:-vidu2.0}}"
VIDU_MATERIAL_PUBLISH_SCRIPT="${STEVEN_LOOP_VIDU_MATERIAL_PUBLISH_SCRIPT:-${BARRY_LOOP_VIDU_MATERIAL_PUBLISH_SCRIPT:-$HOME/.codex/skills/beidou-novel-ops/scripts/vidu_material_publish.js}}"
VIDU_MATERIAL_POOL_DIR="${STEVEN_LOOP_VIDU_MATERIAL_POOL_DIR:-${BARRY_LOOP_VIDU_MATERIAL_POOL_DIR:-$ROOT_DIR/runtime/vidu-material-pool}}"
VIDU_MATERIAL_COUNT="${STEVEN_LOOP_VIDU_MATERIAL_COUNT:-${BARRY_LOOP_VIDU_MATERIAL_COUNT:-1}}"
LOCK_FILE="${STEVEN_JIAO_AI_LOOP_LOCK_FILE:-$ROOT_DIR/runtime/steven-jiao-ai-loop.lock}"
PUSH_DAILY_REPORT="${STEVEN_FEISHU_DAILY_LOOP_REPORT_PUSH:-${BARRY_FEISHU_DAILY_LOOP_REPORT_PUSH:-0}}"
PUSH_ROUND_REPORT="${STEVEN_FEISHU_DAILY_LOOP_ROUND_REPORT_PUSH:-${BARRY_FEISHU_DAILY_LOOP_ROUND_REPORT_PUSH:-0}}"
DELETE_REPORT_AFTER_PUSH="${STEVEN_FEISHU_DELETE_LOCAL_REPORT_AFTER_PUSH:-${BARRY_FEISHU_DELETE_LOCAL_REPORT_AFTER_PUSH:-0}}"

TODAY="$(date +%F)"
RUN_DIR="$STATE_ROOT/$TODAY"
PID_FILE="$RUN_DIR/scheduler.pid"
LOG_FILE="$RUN_DIR/scheduler.log"
REPORT_FILE="$REPORT_DIR/日常自动发布报告_$(date +%Y%m%d).md"

mkdir -p "$RUN_DIR" "$REPORT_DIR"
touch "$LOG_FILE"
mkdir -p "$(dirname "$LOCK_FILE")"
LOCK_DIR="${LOCK_FILE}.d"
LOCK_HELD=0
LOCK_USES_DIR=0
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    printf '[%s] Steven Jiao AI Loop 已有实例在运行，跳过重复启动。\n' "$(date '+%F %T')" | tee -a "$LOG_FILE"
    exit 0
  fi
  LOCK_HELD=1
else
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
      printf '[%s] Steven Jiao AI Loop 已有实例在运行，跳过重复启动。\n' "$(date '+%F %T')" | tee -a "$LOG_FILE"
      exit 0
    fi
    rmdir "$LOCK_DIR" 2>/dev/null || true
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
      printf '[%s] Steven Jiao AI Loop 已有实例在运行，跳过重复启动。\n' "$(date '+%F %T')" | tee -a "$LOG_FILE"
      exit 0
    fi
  fi
  LOCK_HELD=1
  LOCK_USES_DIR=1
fi

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG_FILE"
}

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    log "今日调度器已在运行，pid=${EXISTING_PID}，跳过重复启动。"
    exit 0
  fi
fi

echo "$$" > "$PID_FILE"
cleanup() {
  rm -f "$PID_FILE"
  if [[ "$LOCK_HELD" == "1" && "$LOCK_USES_DIR" == "1" ]]; then
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
}
trap cleanup EXIT

round_label() {
  local round_no="${1#round}"
  if [[ "$round_no" =~ ^[0-9]+$ ]]; then
    echo "第 ${round_no} 轮"
  else
    echo "$1"
  fi
}

round_time() {
  local round_no="${1#round}"
  local direct_var="ROUND${round_no}_AT"
  local steven_var="STEVEN_LOOP_ROUND${round_no}_AT"
  local barry_var="BARRY_LOOP_ROUND${round_no}_AT"
  if [[ -n "${!direct_var:-}" ]]; then
    echo "${!direct_var}"
    return 0
  fi
  if [[ -n "${!steven_var:-}" ]]; then
    echo "${!steven_var}"
    return 0
  fi
  if [[ -n "${!barry_var:-}" ]]; then
    echo "${!barry_var}"
    return 0
  fi
  case "$1" in
    round1) echo "$ROUND1_AT" ;;
    round2) echo "$ROUND2_AT" ;;
    round3) echo "$ROUND3_AT" ;;
    round4) echo "$ROUND4_AT" ;;
    round5) echo "$ROUND5_AT" ;;
    round6) echo "$ROUND6_AT" ;;
    round7) echo "$ROUND7_AT" ;;
    round8) echo "$ROUND8_AT" ;;
    round9) echo "$ROUND9_AT" ;;
    round10) echo "$ROUND10_AT" ;;
    *) echo "23:59" ;;
  esac
}

round_kind() {
  local round_no="${1#round}"
  local direct_var="ROUND${round_no}_KIND"
  local steven_var="STEVEN_LOOP_ROUND${round_no}_KIND"
  local barry_var="BARRY_LOOP_ROUND${round_no}_KIND"
  if [[ -n "${!direct_var:-}" ]]; then
    echo "${!direct_var}"
    return 0
  fi
  if [[ -n "${!steven_var:-}" ]]; then
    echo "${!steven_var}"
    return 0
  fi
  if [[ -n "${!barry_var:-}" ]]; then
    echo "${!barry_var}"
    return 0
  fi
  case "$1" in
    round1) echo "$ROUND1_KIND" ;;
    round2) echo "$ROUND2_KIND" ;;
    round3) echo "$ROUND3_KIND" ;;
    round4) echo "$ROUND4_KIND" ;;
    round5) echo "$ROUND5_KIND" ;;
    round6) echo "$ROUND6_KIND" ;;
    round7) echo "$ROUND7_KIND" ;;
    round8) echo "$ROUND8_KIND" ;;
    round9) echo "$ROUND9_KIND" ;;
    round10) echo "$ROUND10_KIND" ;;
    *) echo "batch_drama" ;;
  esac
}

round_clip_engine() {
  local round_no="${1#round}"
  local direct_var="ROUND${round_no}_CLIP_ENGINE"
  local steven_var="STEVEN_LOOP_ROUND${round_no}_CLIP_ENGINE"
  local barry_var="BARRY_LOOP_ROUND${round_no}_CLIP_ENGINE"
  if [[ -n "${!direct_var:-}" ]]; then
    echo "${!direct_var}"
    return 0
  fi
  if [[ -n "${!steven_var:-}" ]]; then
    echo "${!steven_var}"
    return 0
  fi
  if [[ -n "${!barry_var:-}" ]]; then
    echo "${!barry_var}"
    return 0
  fi
  case "$1" in
    round1) echo "$ROUND1_CLIP_ENGINE" ;;
    round2) echo "$ROUND2_CLIP_ENGINE" ;;
    round3) echo "$ROUND3_CLIP_ENGINE" ;;
    round4) echo "$ROUND4_CLIP_ENGINE" ;;
    round5) echo "$ROUND5_CLIP_ENGINE" ;;
    round6) echo "$ROUND6_CLIP_ENGINE" ;;
    round7) echo "$ROUND7_CLIP_ENGINE" ;;
    round8) echo "$ROUND8_CLIP_ENGINE" ;;
    round9) echo "$ROUND9_CLIP_ENGINE" ;;
    round10) echo "$ROUND10_CLIP_ENGINE" ;;
    *) echo "$DEFAULT_CLIP_ENGINE" ;;
  esac
}

round_summary_path() {
  echo "$RUN_DIR/$1.summary"
}

truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

team_id_count() {
  local file="$1"
  if [[ -z "$file" || ! -f "$file" ]]; then
    echo 0
    return 0
  fi
  awk 'NF && $1 !~ /^#/ { count += 1 } END { print count + 0 }' "$file"
}

run_batch_drama_variant() {
  local round="$1"
  local label="$2"
  local variant_label="$3"
  local team_ids_file="$4"
  local clip_engine="$5"
  local output_json="$6"
  local round_push_value="$7"
  local variant_count
  variant_count="$(team_id_count "$team_ids_file")"
  if (( variant_count <= 0 )); then
    log "${label} ${variant_label} 账号池为空，跳过。"
    return 1
  fi

  local -a variant_cmd=(
    env
    "BARRY_FEISHU_TEST_PUSH=$round_push_value"
    "STEVEN_LOOP_CURRENT_ROUND_NO=${round#round}"
    "STEVEN_LOOP_AB_GROUP=$variant_label"
    python3 backend/flywheel_cli.py run-batch-drama
    --execute
    --count "$variant_count"
    --publish-platform "$PLATFORM"
    --candidate-source "$CANDIDATE_SOURCE"
    --clip-engine "$clip_engine"
    --publish-retries "${STEVEN_LOOP_PUBLISH_RETRIES:-${BARRY_LOOP_PUBLISH_RETRIES:-0}}"
    --collect-wait-seconds "$COLLECT_WAIT_SECONDS"
    --collect-poll-interval "$COLLECT_POLL_INTERVAL"
    --download-dir "$RUN_DIR/clips-${round}-${variant_label}"
    --json
  )
  if [[ "$ALLOW_ACCOUNT_REUSE" == "1" ]]; then
    variant_cmd+=(--allow-account-reuse)
  fi
  while IFS= read -r team_id; do
    [[ -n "$team_id" ]] || continue
    [[ "$team_id" =~ ^# ]] && continue
    variant_cmd+=(--team-id "$team_id")
  done < "$team_ids_file"

  log "${label} ${variant_label} 开始：账号=${variant_count}，剪辑引擎=${clip_engine}，账号池=${team_ids_file}。"
  if "${variant_cmd[@]}" >"$output_json" 2>>"$LOG_FILE"; then
    log "${label} ${variant_label} 完成。"
    return 0
  fi
  log "${label} ${variant_label} 命令返回非零，继续保留结果用于汇总。"
  return 1
}

merge_ab_round_json() {
  local output_json="$1"
  local a_json="$2"
  local b_json="$3"
  local a_label="$4"
  local b_label="$5"
  python3 - "$output_json" "$a_json" "$b_json" "$a_label" "$b_label" <<'PY'
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
inputs = [(Path(sys.argv[2]), sys.argv[4]), (Path(sys.argv[3]), sys.argv[5])]
payloads = []
items = []
requested = 0
for path, label in inputs:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        payload = {"status": "error", "error": str(exc), "items": []}
    variant_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    for item in variant_items:
        if isinstance(item, dict):
            item["ab_group"] = label
            item.setdefault("experiment", {})["name"] = "shortdrama_clip_engine_ab"
            item.setdefault("experiment", {})["group"] = label
    requested += int(payload.get("requested_count") or len(variant_items) or 0)
    payloads.append({"label": label, "path": str(path), "status": payload.get("status"), "requested_count": payload.get("requested_count") or len(variant_items)})
    items.extend(variant_items)

success = 0
failed = 0
processing = 0
for item in items:
    status = str((item or {}).get("status") or "")
    if status == "failed":
        failed += 1
    elif status in {"published_submitted", "publish_processing", "processing"}:
        processing += 1
    elif status in {"published", "success", "posted"}:
        success += 1
planned = len(items)
merged = {
    "status": "done",
    "mode": "batch_drama_ab",
    "experiment": {
        "name": "shortdrama_clip_engine_ab",
        "groups": payloads,
    },
    "requested_count": requested or planned,
    "items": items,
    "report_zh": {
        "请求数量": requested or planned,
        "计划数量": planned,
        "发布成功数": success,
        "失败数": failed,
        "发布处理中数": processing,
    },
}
output.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

round_done() {
  local summary
  summary="$(round_summary_path "$1")"
  [[ -f "$summary" ]] || return 1
  ! grep -Eq '^status=error$' "$summary"
}

current_hhmm() {
  date +%H:%M
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

write_daily_report() {
  python3 - "$RUN_DIR" "$REPORT_FILE" "$TODAY" "$PLATFORM" "$COUNT" "$MIN_SUCCESS_TARGET" <<'PY'
import os
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
report_file = Path(sys.argv[2])
today = sys.argv[3]
platform = sys.argv[4]
count = int(sys.argv[5])
target = int(sys.argv[6])

rows = []
for path in sorted(run_dir.glob("*.summary")):
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    if data:
        rows.append(data)

def as_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default

total_requested = sum(as_int(row.get("requested_count", "0")) for row in rows if row.get("status") == "done")
total_success = sum(as_int(row.get("success_count", "0")) for row in rows if row.get("status") == "done")
total_failed = sum(as_int(row.get("failed_count", "0")) for row in rows if row.get("status") == "done")
total_unsubmitted = sum(as_int(row.get("unsubmitted_count", "0")) for row in rows if row.get("status") == "done")

lines = [
    "# 日常自动发布报告",
    "",
    f"**日期**: {today}",
    f"**目标平台**: {platform}",
    f"**计划目标**: 多轮补跑，累计成功达到 {target} 条后停止后续轮次；单轮计划 {count} 条",
    "",
    "---",
    "",
    "## 总体概览",
    "",
    "| 指标 | 数值 |",
    "| --- | --- |",
    f"| 已执行轮次 | {sum(1 for row in rows if row.get('status') == 'done')} 轮 |",
    f"| 累计请求发布数 | {total_requested} 条 |",
    f"| 累计发布成功 | {total_success} 条 |",
    f"| 累计发布失败 | {total_failed} 条 |",
    f"| 累计未提交 | {total_unsubmitted} 条 |",
    "",
    "## 各轮结果",
    "",
    "| 轮次 | 计划时间 | 实际开始 | 请求数 | 成功 | 失败 | 未提交 | 报告文件 |",
    "| --- | --- | --- | --- | --- | --- | --- | --- |",
]

for row in rows:
    label = row.get("label", row.get("round", ""))
    lines.append(
        "| {label} | {scheduled} | {started} | {requested} | {success} | {failed} | {unsubmitted} | {report} |".format(
            label=label,
            scheduled=row.get("scheduled_time", ""),
            started=row.get("started_at", ""),
            requested=row.get("requested_count", "-"),
            success=row.get("success_count", "-"),
            failed=row.get("failed_count", "-"),
            unsubmitted=row.get("unsubmitted_count", "-"),
            report=row.get("report_file", ""),
        )
    )

lines.extend(
    [
        "",
        "## 结论",
        "",
        (
            f"- 当前累计成功 {total_success} 条。"
            + ("已达到保底目标。" if total_success >= target else "尚未达到保底目标。")
        ),
        "- 详细单轮任务明细仍以各次批量发布测试报告为准。",
    ]
)

report_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY
}


build_round_telemetry() {
  local round="$1"
  if [[ ! -x "$ROOT_DIR/scripts/build_loop_telemetry.py" ]]; then
    return 0
  fi
  if output="$(python3 "$ROOT_DIR/scripts/build_loop_telemetry.py" --date "$TODAY" --round "$round" 2>>"$LOG_FILE")"; then
    log "$(round_label "$round") telemetry 已生成：${output}。"
  else
    log "$(round_label "$round") telemetry 生成失败，详情见日志。"
  fi
}

import_round_telemetry_to_dashboard() {
  local round="$1"
  if [[ "${STEVEN_LOOP_DASHBOARD_IMPORT_ENABLED:-1}" == "0" ]]; then
    return 0
  fi
  if [[ ! -f "$ROOT_DIR/scripts/import_steven_telemetry.py" ]]; then
    return 0
  fi
  local output
  if output="$(python3 "$ROOT_DIR/scripts/import_steven_telemetry.py" \
    --loop-root "$ROOT_DIR" \
    --date "$TODAY" \
    --api-base "${STEVEN_LOOP_DASHBOARD_API_BASE:-http://127.0.0.1:8770}" \
    --execute \
    --batch-size "${STEVEN_LOOP_DASHBOARD_IMPORT_BATCH_SIZE:-500}" 2>>"$LOG_FILE")"; then
    log "$(round_label "$round") telemetry 已导入看板库：${output}。"
  else
    log "$(round_label "$round") telemetry 导入看板库失败，详情见日志。"
  fi
}

push_daily_report() {
  if [[ "$PUSH_DAILY_REPORT" != "1" && "$PUSH_DAILY_REPORT" != "true" && "$PUSH_DAILY_REPORT" != "yes" && "$PUSH_DAILY_REPORT" != "on" ]]; then
    return 0
  fi
  python3 - "$REPORT_FILE" "$PLATFORM" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "backend")
import flywheel_cli as f

report_file = Path(sys.argv[1])
platform = sys.argv[2]
if not report_file.exists():
    raise SystemExit(0)

content = report_file.read_text(encoding="utf-8").strip()
if not content:
    raise SystemExit(0)

token = f._feishu_get_tenant_access_token()
receive_id_type, receive_id = f._feishu_receive_target()
result = f._feishu_send_text_message(
    token,
    receive_id_type=receive_id_type,
    receive_id=receive_id,
    text=content,
)
print(str(result.get("message_id") or ""))
PY
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

run_round() {
  local round="$1"
  local label scheduled started json_path summary_path kind
  label="$(round_label "$round")"
  scheduled="$(round_time "$round")"
  started="$(date '+%F %T')"
  json_path="$RUN_DIR/$round.json"
  summary_path="$(round_summary_path "$round")"
  kind="$(round_kind "$round")"

  log "${label} 开始执行，类型=${kind}，目标平台=${PLATFORM}，计划数量=${COUNT}。"

  local round_push_value=0
  if [[ "$PUSH_ROUND_REPORT" == "1" || "$PUSH_ROUND_REPORT" == "true" || "$PUSH_ROUND_REPORT" == "yes" || "$PUSH_ROUND_REPORT" == "on" ]]; then
    round_push_value=1
  fi

  local cmd=()
  local command_already_ran=0
  case "$kind" in
    vidu_growth_startend)
      cmd=(
        node "$VIDU_GROWTH_SCRIPT"
        --scheme startend
        --platform "$PLATFORM"
        --variant-count "$VIDU_GROWTH_VARIANTS"
        --team-ids-file "$VIDU_GROWTH_TEAM_IDS_FILE"
        --duration "$VIDU_GROWTH_DURATION"
        --resolution "$VIDU_GROWTH_RESOLUTION"
        --model "$VIDU_GROWTH_MODEL"
        --require-audio true
      )
      log "${label} 使用Vidu养号AB实验A组：简介生成首尾帧 -> Vidu首尾帧生视频。"
      ;;
    vidu_growth_img2video)
      cmd=(
        node "$VIDU_GROWTH_SCRIPT"
        --scheme img2video
        --platform "$PLATFORM"
        --variant-count "$VIDU_GROWTH_VARIANTS"
        --team-ids-file "$VIDU_GROWTH_TEAM_IDS_FILE"
        --duration "$VIDU_GROWTH_DURATION"
        --resolution "$VIDU_GROWTH_RESOLUTION"
        --model "$VIDU_GROWTH_MODEL"
        --require-audio true
      )
      log "${label} 使用Vidu养号AB实验B组：北斗海报 + 简介 -> Vidu图生视频。"
      ;;
    vidu_material_publish)
      cmd=(
        node "$VIDU_MATERIAL_PUBLISH_SCRIPT"
        --pool-dir "$VIDU_MATERIAL_POOL_DIR"
        --team-ids-file "$VIDU_GROWTH_TEAM_IDS_FILE"
        --count "$VIDU_MATERIAL_COUNT"
        --require-audio true
      )
      log "${label} 使用Vidu素材池发布：到点只取ready素材发布，不现场生成。"
      ;;
    batch_drama)
      local clip_engine
      clip_engine="$(round_clip_engine "$round")"
      if truthy "$AB_ENABLED"; then
        local a_json b_json
        a_json="$RUN_DIR/${round}.A.json"
        b_json="$RUN_DIR/${round}.B.json"
        run_batch_drama_variant "$round" "$label" "$AB_GROUP_A_LABEL" "$AB_GROUP_A_TEAM_IDS_FILE" "$AB_GROUP_A_CLIP_ENGINE" "$a_json" "$round_push_value" &
        local a_pid=$!
        run_batch_drama_variant "$round" "$label" "$AB_GROUP_B_LABEL" "$AB_GROUP_B_TEAM_IDS_FILE" "$AB_GROUP_B_CLIP_ENGINE" "$b_json" "$round_push_value" &
        local b_pid=$!
        wait "$a_pid" || true
        wait "$b_pid" || true
        merge_ab_round_json "$json_path" "$a_json" "$b_json" "$AB_GROUP_A_LABEL" "$AB_GROUP_B_LABEL"
        command_already_ran=1
        log "${label} AB实验合并完成：A=${AB_GROUP_A_CLIP_ENGINE}，B=${AB_GROUP_B_CLIP_ENGINE}。"
      else
        cmd=(
          env BARRY_FEISHU_TEST_PUSH="$round_push_value"
          python3 backend/flywheel_cli.py run-batch-drama
          --execute
          --count "$COUNT"
          --publish-platform "$PLATFORM"
          --candidate-source "$CANDIDATE_SOURCE"
          --clip-engine "$clip_engine"
          --publish-retries "${STEVEN_LOOP_PUBLISH_RETRIES:-${BARRY_LOOP_PUBLISH_RETRIES:-0}}"
          --collect-wait-seconds "$COLLECT_WAIT_SECONDS"
          --collect-poll-interval "$COLLECT_POLL_INTERVAL"
          --json
        )
        cmd=(env "STEVEN_LOOP_CURRENT_ROUND_NO=${round#round}" "${cmd[@]}")
        log "${label} 使用候选源：${CANDIDATE_SOURCE}，剪辑引擎：${clip_engine}。"
        if [[ "$ALLOW_ACCOUNT_REUSE" == "1" ]]; then
          cmd+=(--allow-account-reuse)
        fi
        if [[ -n "$TEAM_IDS_FILE" && -f "$TEAM_IDS_FILE" ]]; then
          while IFS= read -r team_id; do
            [[ -n "$team_id" ]] || continue
            [[ "$team_id" =~ ^# ]] && continue
            cmd+=(--team-id "$team_id")
          done < "$TEAM_IDS_FILE"
          log "${label} 使用指定账号池文件：${TEAM_IDS_FILE}。"
        fi
        if [[ -n "$TEAM_IDS" ]]; then
          IFS=',' read -r -a inline_team_ids <<<"$TEAM_IDS"
          local team_id
          for team_id in "${inline_team_ids[@]}"; do
            team_id="${team_id#"${team_id%%[![:space:]]*}"}"
            team_id="${team_id%"${team_id##*[![:space:]]}"}"
            [[ -n "$team_id" ]] && cmd+=(--team-id "$team_id")
          done
          log "${label} 使用环境变量指定账号池。"
        fi
      fi
      ;;
    *)
      log "${label} 未知轮次类型：${kind}。"
      return 1
      ;;
  esac

  if [[ "$command_already_ran" != "1" ]]; then
    if "${cmd[@]}" >"$json_path" 2>>"$LOG_FILE"; then
      :
    else
      log "$label 命令执行返回非零状态，继续按结果文件尝试汇总。"
    fi
  fi

  python3 - "$json_path" "$summary_path" "$round" "$label" "$scheduled" "$started" <<'PY'
import json
import sys
from pathlib import Path

json_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
round_name = sys.argv[3]
label = sys.argv[4]
scheduled = sys.argv[5]
started = sys.argv[6]

payload = {}
try:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
except Exception:
    payload = {}

report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
requested = int(payload.get("requested_count") or report.get("请求数量") or 0)
success = int(report.get("发布成功数") or 0)
failed = int(report.get("失败数") or 0)
processing = int(report.get("发布处理中数") or 0)
planned = int(report.get("计划数量") or requested or 0)
unsubmitted = max(planned - success - failed - processing, 0)
status = "done" if payload else "error"

report_files = payload.get("test_report_files") if isinstance(payload.get("test_report_files"), dict) else {}
report_file = str(report_files.get("markdown") or "")

lines = [
    f"round={round_name}",
    f"label={label}",
    f"scheduled_time={scheduled}",
    f"started_at={started}",
    f"status={status}",
    f"requested_count={requested}",
    f"planned_count={planned}",
    f"success_count={success}",
    f"failed_count={failed}",
    f"processing_count={processing}",
    f"unsubmitted_count={unsubmitted}",
    f"report_file={report_file}",
]
summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

  write_daily_report
  build_round_telemetry "$round"
  import_round_telemetry_to_dashboard "$round"
  log "$label 执行完成。"
}

wait_until_round_time() {
  local round="$1"
  local scheduled now
  scheduled="$(round_time "$round")"
  while true; do
    now="$(current_hhmm)"
    if [[ "$now" > "$scheduled" || "$now" == "$scheduled" ]]; then
      return 0
    fi
    sleep 30
  done
}

maybe_run_round() {
  local round="$1"
  local round_no="${round#round}"
  if (( round_no > MAX_ROUNDS )); then
    return 0
  fi
  if round_done "$round"; then
    return 0
  fi
  wait_until_round_time "$round"
  if (( round_no > 1 )); then
    local total_success
    total_success="$(sum_success)"
    if (( total_success >= MIN_SUCCESS_TARGET )); then
      cat >"$(round_summary_path "$round")" <<EOF
round=$round
label=$(round_label "$round")
scheduled_time=$(round_time "$round")
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
      log "$(round_label "$round") 跳过，当前累计成功 $total_success 条，已达到保底目标。"
      return 0
    fi
  fi
  run_round "$round"
}

log "日常调度器启动。平台=${PLATFORM}，每轮=${COUNT}，保底成功目标=${MIN_SUCCESS_TARGET}。"
log "发布排期：enabled=${PUBLISH_SCHEDULE_ENABLED}，窗口=${PUBLISH_TIMEZONE} ${PUBLISH_WINDOW_START}-次日${PUBLISH_WINDOW_END}，lead=${PUBLISH_LEAD_MINUTES}分钟。"

for round_no in $(seq 1 "$MAX_ROUNDS"); do
  maybe_run_round "round${round_no}"
done

write_daily_report
if message_id="$(push_daily_report 2>>"$LOG_FILE")"; then
  if [[ -n "$message_id" ]]; then
    log "今日测试报告已推送到飞书，message_id=${message_id}。"
    delete_daily_reports_after_push
  fi
else
  log "今日测试报告飞书推送失败，详情见日志。"
fi
log "今日调度器结束。累计成功 $(sum_success) 条，请求总数 $(sum_requested) 条，失败 $(sum_failed) 条，未提交 $(sum_unsubmitted) 条。"
