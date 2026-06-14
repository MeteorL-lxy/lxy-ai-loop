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
export BARRY_DAILY_CLEANUP_AT="${BARRY_DAILY_CLEANUP_AT:-19:30}"
export BARRY_DAILY_CLEANUP_STATE_ROOT="${BARRY_DAILY_CLEANUP_STATE_ROOT:-$ROOT_DIR/data/daily-cleanup}"
export BARRY_FEISHU_DAILY_CLEANUP_PUSH="${BARRY_FEISHU_DAILY_CLEANUP_PUSH:-1}"

exec "$ROOT_DIR/scripts/run-daily-artifact-cleanup-scheduler.sh" "$@"
