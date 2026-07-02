#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${BARRY_SERVER_ENV_FILE:-$ROOT_DIR/.env.server}"

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

export BARRY_VIDEO_API_ENV="${BARRY_VIDEO_API_ENV:-test}"
export BARRY_LOOP_PLATFORM="${BARRY_LOOP_PLATFORM:-FACEBOOK}"
export BARRY_LOOP_COUNT="${BARRY_LOOP_COUNT:-0}"
export BARRY_LOOP_ACCOUNT_SUCCESS_TARGET="${BARRY_LOOP_ACCOUNT_SUCCESS_TARGET:-10}"
export BARRY_LOOP_ALLOW_ACCOUNT_REUSE="${BARRY_LOOP_ALLOW_ACCOUNT_REUSE:-1}"
export BARRY_LOOP_ACCOUNT_POOL="${BARRY_LOOP_ACCOUNT_POOL:-}"
export BARRY_LOOP_REALTIME_ACCOUNT_POOL="${BARRY_LOOP_REALTIME_ACCOUNT_POOL:-facebook_drama_realtime_pool}"
export BARRY_LOOP_ORDINARY_ACCOUNT_POOL="${BARRY_LOOP_ORDINARY_ACCOUNT_POOL:-facebook_drama_ordinary_pool}"
export BARRY_LOOP_FBHOT_TEST_ACCOUNT_POOL="${BARRY_LOOP_FBHOT_TEST_ACCOUNT_POOL:-facebook_drama_fbhot_test_pool}"
export BARRY_LOOP_CREATIVE_LIST_ACCOUNT_POOL="${BARRY_LOOP_CREATIVE_LIST_ACCOUNT_POOL:-facebook_drama_creative_list_pool}"
export BARRY_LOOP_CREATIVE_LIST_DAY_ACCOUNT_POOL="${BARRY_LOOP_CREATIVE_LIST_DAY_ACCOUNT_POOL:-facebook_drama_creative_list_day_pool}"
export BARRY_LOOP_REALTIME_DAY_ACCOUNT_POOL="${BARRY_LOOP_REALTIME_DAY_ACCOUNT_POOL:-facebook_drama_realtime_day_pool}"
export BARRY_LOOP_REALTIME_SINGLE_ACCOUNT_POOL="${BARRY_LOOP_REALTIME_SINGLE_ACCOUNT_POOL:-facebook_drama_realtime_single_pool}"
export BARRY_LOOP_YOURCHANNEL_ACCOUNT_POOL="${BARRY_LOOP_YOURCHANNEL_ACCOUNT_POOL:-facebook_drama_yourchannel_pool}"
export BARRY_LOOP_RECENT_ORDER_ACCOUNT_POOL="${BARRY_LOOP_RECENT_ORDER_ACCOUNT_POOL:-facebook_drama_recent_order_pool}"
export BARRY_LOOP_STARDUSTTV_ACCOUNT_POOL="${BARRY_LOOP_STARDUSTTV_ACCOUNT_POOL:-facebook_drama_stardusttv_pool}"
export BARRY_LOOP_RESET_TARGETS_ON_START="${BARRY_LOOP_RESET_TARGETS_ON_START:-0}"
export BARRY_LOOP_STATE_ROOT="${BARRY_LOOP_STATE_ROOT:-$ROOT_DIR/runtime/continuous-loop}"
export BARRY_LOOP_REPORT_DIR="${BARRY_LOOP_REPORT_DIR:-$ROOT_DIR/runtime/reports/continuous-test-summary}"
export BARRY_VIDEO_TEST_SUMMARY_DIR="${BARRY_VIDEO_TEST_SUMMARY_DIR:-$ROOT_DIR/runtime/reports/continuous-test-summary}"
export BARRY_FEISHU_DAILY_LOOP_REPORT_PUSH="${BARRY_FEISHU_DAILY_LOOP_REPORT_PUSH:-0}"
export BARRY_FEISHU_DAILY_LOOP_REPORT_DELAY_SECONDS="${BARRY_FEISHU_DAILY_LOOP_REPORT_DELAY_SECONDS:-0}"

exec "$ROOT_DIR/scripts/run-dual-line-forever.sh" "$@"
