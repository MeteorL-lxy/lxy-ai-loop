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

cd "$ROOT_DIR"

export BARRY_VIDEO_API_ENV="${BARRY_VIDEO_API_ENV:-test}"
export BARRY_VIDEO_ANALYSIS_SUMMARY_DIR="${BARRY_VIDEO_ANALYSIS_SUMMARY_DIR:-$ROOT_DIR/runtime/reports/analysis}"
export BARRY_ANALYSIS_WINDOW_DAYS="${BARRY_ANALYSIS_WINDOW_DAYS:-1}"
export BARRY_ANALYSIS_LAG_DAYS="${BARRY_ANALYSIS_LAG_DAYS:-2}"
export BARRY_ANALYSIS_STATE_DIR="${BARRY_ANALYSIS_STATE_DIR:-$ROOT_DIR/runtime/analysis-daily}"

mkdir -p "$BARRY_ANALYSIS_STATE_DIR"
LOCK_DIR="$BARRY_ANALYSIS_STATE_DIR/publish-analysis.lock"
LOCK_PID_FILE="$LOCK_DIR/pid"

is_live_analysis_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  local cmdline=""
  if [[ -r "/proc/$pid/cmdline" ]]; then
    cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
  else
    cmdline="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  fi
  [[ "$cmdline" == *"backend/flywheel_cli.py publish-analysis-daily"* ]] || [[ "$cmdline" == *"scripts/run-server-analysis-daily.sh"* ]]
}

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$LOCK_PID_FILE"
    return 0
  fi

  local existing_pid=""
  if [[ -f "$LOCK_PID_FILE" ]]; then
    existing_pid="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
  fi
  if is_live_analysis_pid "$existing_pid"; then
    echo "publish-analysis-daily already running, skip duplicate start. pid=${existing_pid}"
    return 1
  fi

  rm -rf "$LOCK_DIR"
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$LOCK_PID_FILE"
    echo "publish-analysis-daily found stale lock, reclaimed it."
    return 0
  fi

  echo "publish-analysis-daily failed to acquire lock."
  return 1
}

if ! acquire_lock; then
  exit 0
fi
cleanup() {
  rm -f "$LOCK_PID_FILE" 2>/dev/null || true
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

python3 backend/flywheel_cli.py publish-analysis-daily \
  --platform FACEBOOK \
  --window-days "$BARRY_ANALYSIS_WINDOW_DAYS" \
  --lag-days "$BARRY_ANALYSIS_LAG_DAYS" \
  --write-snapshot \
  "$@"
