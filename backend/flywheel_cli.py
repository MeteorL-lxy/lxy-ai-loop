#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timedelta
import hashlib
import json
import os
import random
import re
import requests
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from inbeidou_cli import (
    API_ENV,
    DEFAULT_HIGH_CUT_CONFIG,
    DEFAULT_DEDUPLICATION,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TASK_TIMEOUT,
    DEDUPLICATION_CHOICES,
    HIGH_CUT_CHOICES,
    HIGH_CUT_TASK_KEY,
    InbeidouError,
    PROMOTION_PLATFORMS,
    active_task,
    build_promotion_link_entry,
    build_high_cut_params,
    create_publish_post,
    download_manus,
    format_seconds,
    format_size,
    get_creator_enum,
    get_episode_info,
    get_episode_list,
    get_income_aggregation,
    get_income_click_aggregation,
    get_my_task_list,
    get_publish_analysis,
    get_publish_accounts,
    get_publish_records,
    normalize_publish_platform,
    probe_video,
    receive_task,
    require_success,
    load_state,
    resolve_drama_episode_context,
    resolve_publish_targets,
    save_state,
    submit_ws_tasks,
    upload_publish_file,
    upload_video,
    wait_for_manus,
)
from flywheel.config import DEFAULT_CONFIG_PATH, load_config
from flywheel.db.sqlite_local import FlywheelSQLite
from flywheel.publishing.publish_executor import _ensure_vertical_publish_file
from flywheel.publishing.constraints import (
    validate_publish_clip_constraints,
    validate_promotion_constraints,
    validate_source_episode_constraints,
)
from flywheel.publishing.account_sync import sync_publish_accounts
from flywheel.scoring.aggregator import score_candidate
from flywheel.reporting import (
    _app_label,
    _dedup_zh,
    _language_zh,
    _platform_label,
    _status_zh,
    build_round_report_zh,
    build_round_user_summary_zh,
    parse_stage_rows,
)
from flywheel.account_profiles import build_account_assignment_profiles
from flywheel import batch_drama_cli as batch_drama_cli_module
from flywheel import publish_reporting as publish_reporting_module
from flywheel.feishu_cards import build_analysis_feishu_card, build_test_feishu_card
from flywheel.selection.candidate_pool import fetch_candidates
from flywheel.selection.history_filter import candidate_history_keys, candidate_serial_ids, split_recent_candidates
from flywheel.selection.realtime_rank_source import fetch_realtime_rank_candidates
from flywheel.clipping.episode_selector import _episode_api_with_retries, select_best_episode
from flywheel.clipping.ai_cut_animation import (
    AiCutAnimationError,
    choose_success_segment,
    create_short_drama_clip_task,
    describe_serial_failure,
    download_segment_video,
    wait_for_serial_success_segment,
    wait_for_short_drama_clip_task,
)

RUNNING_PUBLISH_STATUSES = {"WAITING", "PENDING", "PROCESSING", "QUEUED", "SUBMITTED", "SCHEDULED"}
SUCCESSFUL_PUBLISH_STATUSES = {"POSTED", "SUCCESS", "DONE"}
CLIP_SUPPORTED_DRAMA_PLATFORMS = ["kalos", "snackshort", "goodshort", "moboreels", "touchshort", "flickreels", "stardusttv"]
CLIP_SUPPORTED_DRAMA_PLATFORM_ALIASES = {
    "kalostv": "kalos",
    "kalos": "kalos",
    "snackshort": "snackshort",
    "goodshort": "goodshort",
    "moboreels": "moboreels",
    "touchshort": "touchshort",
    "flickreels": "flickreels",
    "stardusttv": "stardusttv",
}
CUT_TYPE_ZH = {
    "high_cut": "高燃卡点",
    "golden_three": "黄金三段式",
    "golden_clips": "黄金片段提取",
    "high_pre": "预告向高燃",
    "ai_cut_animation": "AI 自动剪辑",
    "ffmpeg_segment": "FFmpeg 分段快切",
}
FINAL_FAILURE_PUBLISH_STATUSES = {"ERROR", "FAILED"}
FAILED_PUBLISH_STATE_KEY = "barry_video_failed_publish_retry_context"
NON_RETRYABLE_PUBLISH_ERROR_PATTERNS = [
    "账号不能发布reel视频",
    "账号不能发布 reel 视频",
    "cannot publish reel",
    "can't publish reel",
    "not allowed to publish reel",
]
SETTLE_TIMEOUT_FAILURE_REASON = "状态确认超时，未完全收敛；已按失败处理，请稍后手动复核发布记录。"
BATCH_EPISODE_PRECHECK_CONCURRENCY = 4
BATCH_EPISODE_PRECHECK_WINDOW_PADDING = 2
BATCH_EPISODE_PRECHECK_MIN_WINDOW = 3
BATCH_EPISODE_PRECHECK_MAX_WINDOW = 8
BATCH_PLAYABLE_SOURCE_BUFFER = 2
BATCH_SAFETY_GATE_CONCURRENCY = 3
STRATEGY_MEMORY_COOLDOWN_DAYS = 2
STRATEGY_MEMORY_EVENT_TYPES = ("safety_reject", "clip_failed_source_prepare")
HEARTBEAT_INTERVAL_SECONDS = 15
DEFAULT_TEST_SUMMARY_DIR = "/Users/xinyuliu/Downloads/AI Loop/测试总结"
DEFAULT_ANALYSIS_SUMMARY_DIR = "/Users/xinyuliu/Downloads/AI Loop/分析日报"
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
DEFAULT_FEISHU_ENV_FILE = os.getenv("BARRY_FEISHU_ENV_FILE") or str(
    Path(os.getenv("BARRY_VIDEO_AUTH_HOME") or "~/.barry-video").expanduser() / "feishu.env"
)
_FEISHU_ENV_LOADED = False
DEFAULT_SHORT_DRAMA_FACEBOOK_ACCOUNT_POOL = ""
DEFAULT_NOVEL_DOWNLOAD_DIR = Path(
    os.getenv("BARRY_VIDEO_NOVEL_DOWNLOAD_DIR")
    or str(Path.home() / "Downloads" / "barry-video-novels")
).expanduser()
DEFAULT_NOVEL_TMP_DIR = Path(
    os.getenv("BARRY_VIDEO_NOVEL_TMP_DIR")
    or str(Path(tempfile.gettempdir()) / "barry-video-novels")
).expanduser()
DEFAULT_NOVEL_WORK_DIR = Path(
    os.getenv("BARRY_VIDEO_NOVEL_WORK_DIR")
    or str(Path(tempfile.gettempdir()) / "barry-video-novels-work")
).expanduser()
PROJECT_ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_DELETE_ALLOWED_ROOTS = (
    PROJECT_ROOT_DIR / "data" / "flywheel" / "clipped",
    PROJECT_ROOT_DIR / "runtime" / "reports",
    PROJECT_ROOT_DIR / "runtime" / "analysis-daily",
    PROJECT_ROOT_DIR / "runtime" / "daily-loop",
    PROJECT_ROOT_DIR / "runtime" / "continuous-loop",
)
PROJECT_DELETE_PROTECTED_NAMES = {
    ".git",
    "backend",
    "bin",
    "conf",
    "docs",
    "ops",
    "scripts",
    "skills",
    "tools",
}


def _is_relative_to_path(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_cleanup_target(path: Path) -> tuple[bool, str]:
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        return False, f"路径解析失败: {exc}"
    if resolved == PROJECT_ROOT_DIR or PROJECT_ROOT_DIR in resolved.parents:
        rel = resolved.relative_to(PROJECT_ROOT_DIR)
        if rel.parts and rel.parts[0] in PROJECT_DELETE_PROTECTED_NAMES:
            return False, "拒绝删除项目源码/配置目录"
        if not any(_is_relative_to_path(resolved, root.resolve()) for root in PROJECT_DELETE_ALLOWED_ROOTS):
            return False, "拒绝删除非产物区的项目文件"
    if resolved in {Path.home().resolve(), Path(tempfile.gettempdir()).resolve()}:
        return False, "拒绝删除用户目录或系统临时根目录"
    return True, ""


def _load_feishu_env_once() -> None:
    global _FEISHU_ENV_LOADED
    if _FEISHU_ENV_LOADED:
        return
    _FEISHU_ENV_LOADED = True
    env_file = Path(os.getenv("BARRY_FEISHU_ENV_FILE") or DEFAULT_FEISHU_ENV_FILE).expanduser()
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _truthy_env(name: str) -> bool:
    _load_feishu_env_once()
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_truthy_with_default(name: str, *, default: bool) -> bool:
    _load_feishu_env_once()
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _feishu_analysis_push_enabled() -> bool:
    return _truthy_env("BARRY_FEISHU_ANALYSIS_PUSH")


def _feishu_test_push_enabled() -> bool:
    return _env_truthy_with_default("BARRY_FEISHU_TEST_PUSH", default=True)


def _feishu_delete_local_report_after_push_enabled() -> bool:
    return _truthy_env("BARRY_FEISHU_DELETE_LOCAL_REPORT_AFTER_PUSH")


def _feishu_local_video_push_enabled() -> bool:
    return _truthy_env("BARRY_FEISHU_LOCAL_VIDEO_PUSH")


def _feishu_app_id() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_FEISHU_APP_ID") or "").strip()


def _feishu_app_secret() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_FEISHU_APP_SECRET") or "").strip()


def _feishu_target_open_id() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_FEISHU_TARGET_OPEN_ID") or "").strip()


def _feishu_target_user_id() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_FEISHU_TARGET_USER_ID") or "").strip()


def _feishu_target_email() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_FEISHU_TARGET_EMAIL") or "").strip()


def _feishu_timeout_seconds() -> int:
    _load_feishu_env_once()
    raw = str(os.getenv("BARRY_FEISHU_TIMEOUT") or "30").strip()
    try:
        return max(5, int(raw))
    except ValueError:
        return 30


def _loop_round_label() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_LOOP_ROUND_LABEL") or "").strip()


def _loop_round_scheduled_time() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_LOOP_ROUND_SCHEDULED_TIME") or "").strip()


def _loop_round_started_at() -> str:
    _load_feishu_env_once()
    return str(os.getenv("BARRY_LOOP_ROUND_STARTED_AT") or "").strip()


def _feishu_post(path: str, payload: dict[str, object], *, tenant_token: str | None = None) -> dict[str, object]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if tenant_token:
        headers["Authorization"] = f"Bearer {tenant_token}"
    response = requests.post(
        f"{FEISHU_API_BASE}{path}",
        headers=headers,
        json=payload,
        timeout=_feishu_timeout_seconds(),
    )
    raw_text = response.text
    try:
        body = response.json()
    except ValueError:
        body = {"code": response.status_code, "msg": raw_text}
    if response.status_code >= 400:
        raise RuntimeError(f"飞书接口 HTTP {response.status_code}: {body}")
    if int(body.get("code", 0)) != 0:
        raise RuntimeError(f"飞书接口失败: {body.get('msg') or body}")
    data = body.get("data")
    return data if isinstance(data, dict) else body


def _feishu_get_tenant_access_token() -> str:
    app_id = _feishu_app_id()
    app_secret = _feishu_app_secret()
    if not app_id or not app_secret:
        raise RuntimeError("缺少飞书应用凭证，请设置 BARRY_FEISHU_APP_ID / BARRY_FEISHU_APP_SECRET")
    data = _feishu_post(
        "/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
    )
    token = str(data.get("tenant_access_token") or "").strip()
    if not token:
        raise RuntimeError("飞书 tenant_access_token 为空")
    return token


def _feishu_receive_target() -> tuple[str, str]:
    email = _feishu_target_email()
    if email:
        return "email", email
    open_id = _feishu_target_open_id()
    if open_id:
        return "open_id", open_id
    user_id = _feishu_target_user_id()
    if user_id:
        return "user_id", user_id
    raise RuntimeError("缺少飞书接收人，请设置 BARRY_FEISHU_TARGET_EMAIL、BARRY_FEISHU_TARGET_OPEN_ID 或 BARRY_FEISHU_TARGET_USER_ID")


def _analysis_feishu_message_text(payload: dict[str, object]) -> str:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    window = str(report.get("统计窗口") or "").strip() or "-"
    platform = str(report.get("目标平台") or payload.get("platform") or "全部平台").strip() or "全部平台"
    summary = report.get("总体概览") if isinstance(report.get("总体概览"), dict) else {}
    total_posts = summary.get("当日发布视频总数") or 0
    total_success = summary.get("当日发布成功数") or 0
    return (
        "发布数据分析日报卡片发送失败，已跳过错误格式的 markdown 回退。\n"
        f"统计窗口：{window}\n"
        f"目标平台：{platform}\n"
        f"发布总数：{total_posts}\n"
        f"发布成功：{total_success}\n"
        "如需补发正确卡片，可稍后重试分析日报推送。"
    )


def _test_feishu_message_text(payload: dict[str, object]) -> str:
    files = payload.get("test_report_files") if isinstance(payload.get("test_report_files"), dict) else {}
    markdown = str(files.get("markdown") or "").strip()
    if markdown:
        path = Path(markdown).expanduser()
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return _report_markdown(payload).strip()


def _test_feishu_card(payload: dict[str, object]) -> dict[str, object]:
    enriched = dict(payload)
    round_label = _loop_round_label()
    scheduled_time = _loop_round_scheduled_time()
    started_at = _loop_round_started_at()
    if round_label:
        enriched.setdefault("round_label", round_label)
    if scheduled_time:
        enriched.setdefault("round_scheduled_time", scheduled_time)
    if started_at:
        enriched.setdefault("round_started_at", started_at)
    return build_test_feishu_card(
        enriched,
        report_environment_zh=_report_environment_zh,
        reason_counter_rows=_reason_counter_rows,
        failed_publish_suggestions_zh=_failed_publish_suggestions_zh,
    )


def _feishu_send_text_message(tenant_token: str, *, receive_id_type: str, receive_id: str, text: str) -> dict[str, object]:
    return _feishu_post(
        f"/im/v1/messages?receive_id_type={receive_id_type}",
        {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        tenant_token=tenant_token,
    )


def _feishu_send_interactive_message(
    tenant_token: str,
    *,
    receive_id_type: str,
    receive_id: str,
    card: dict[str, object],
) -> dict[str, object]:
    return _feishu_post(
        f"/im/v1/messages?receive_id_type={receive_id_type}",
        {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        },
        tenant_token=tenant_token,
    )


def _delete_report_file_after_push(files: dict[str, object]) -> list[str]:
    if not _feishu_delete_local_report_after_push_enabled():
        return []
    deleted: list[str] = []
    markdown = str(files.get("markdown") or "").strip()
    if markdown:
        path = Path(markdown).expanduser()
        if path.exists() and path.is_file():
            allowed, _reason = _validate_cleanup_target(path)
            if not allowed:
                return deleted
            path.unlink()
            deleted.append(str(path))
    return deleted


def _report_artifact_paths() -> list[str]:
    paths: set[str] = set()
    for directory in {_test_summary_dir(), _analysis_summary_dir()}:
        if not directory.exists():
            continue
        for path in directory.glob("*.md"):
            if path.is_file():
                paths.add(str(path))
    return sorted(paths)


def _today_local_date() -> datetime.date:
    return datetime.now().date()


def _drama_clipped_batch_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "flywheel" / "clipped" / "batch"


def _old_drama_clip_paths() -> list[str]:
    root = _drama_clipped_batch_root()
    if not root.exists() or not root.is_dir():
        return []
    today = _today_local_date()
    paths: list[str] = []
    for child in root.iterdir():
        if not child.is_file():
            continue
        if child.suffix.lower() != ".mp4":
            continue
        try:
            modified_at = datetime.fromtimestamp(child.stat().st_mtime)
        except OSError:
            continue
        if modified_at.date() >= today:
            continue
        paths.append(str(child))
    return sorted(paths)


def _novel_cleanup_grace_hours() -> int:
    raw = os.getenv("BARRY_NOVEL_CLEANUP_GRACE_HOURS", "24")
    try:
        return max(1, min(168, int(raw or "24")))
    except (TypeError, ValueError):
        return 24


def _novel_process_running() -> bool:
    try:
        result = subprocess.run(
            ["ps", "-axo", "command"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    output = str(result.stdout or "")
    return (
        "backend/inbeidou_cli.py novels pipeline" in output
        or "scripts/run-novel-loop-scheduler.sh" in output
        or "scripts/run-server-novel-loop.sh" in output
    )


def _novel_artifact_paths() -> list[str]:
    paths: set[str] = set()
    if _novel_process_running():
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = time.time() - (_novel_cleanup_grace_hours() * 3600)
    candidates = {
        DEFAULT_NOVEL_DOWNLOAD_DIR,
        DEFAULT_NOVEL_TMP_DIR,
        DEFAULT_NOVEL_WORK_DIR,
    }
    for root in candidates:
        if not root.exists() or not root.is_dir():
            continue
        for child in root.iterdir():
            if child.name == today:
                continue
            try:
                modified_at = child.stat().st_mtime
            except OSError:
                continue
            if modified_at >= cutoff:
                continue
            paths.add(str(child))
    return sorted(paths)


def _cleanup_daily_artifacts() -> dict[str, object]:
    state = _get_failed_publish_state()
    failed_items = state.get("items") if isinstance(state.get("items"), list) else []
    failed_clip_paths = _failed_publish_clip_paths([dict(item) for item in failed_items])
    failed_clip_cleanup = _cleanup_generated_files(failed_clip_paths)
    drama_clip_cleanup = _cleanup_generated_files(_old_drama_clip_paths())
    report_cleanup = _cleanup_generated_files(_report_artifact_paths())
    novel_cleanup = _cleanup_generated_files(_novel_artifact_paths())
    _set_failed_publish_state(None)
    deleted_failed = len(failed_clip_cleanup.get("deleted_paths", []))
    deleted_drama_old = len(drama_clip_cleanup.get("deleted_paths", []))
    deleted_reports = len(report_cleanup.get("deleted_paths", []))
    deleted_novel = len(novel_cleanup.get("deleted_paths", []))
    payload: dict[str, object] = {
        "status": "done",
        "mode": "cleanup_daily_artifacts",
        "deleted_failed_publish_files": deleted_failed,
        "deleted_old_drama_clip_files": deleted_drama_old,
        "deleted_report_files": deleted_reports,
        "deleted_novel_artifact_roots": deleted_novel,
        "cleanup": {
            "failed_publish": failed_clip_cleanup,
            "old_drama_clips": drama_clip_cleanup,
            "reports": report_cleanup,
            "novel_artifacts": novel_cleanup,
        },
        "user_summary_zh": (
            f"已清理 {deleted_failed} 个未发布保留成片、{deleted_drama_old} 个历史短剧成片、{deleted_reports} 个残留报告文件和 {deleted_novel} 个小说中间产物目录。"
            if not failed_clip_cleanup.get("errors") and not drama_clip_cleanup.get("errors") and not report_cleanup.get("errors") and not novel_cleanup.get("errors")
            else "已执行每日清理，但有部分文件删除失败。"
        ),
    }
    if state:
        payload["failed_publish_state_cleared"] = True
    return payload


def _maybe_push_feishu_analysis_report(payload: dict[str, object]) -> dict[str, object]:
    if not _feishu_analysis_push_enabled():
        return {}
    existing_marker = _load_analysis_push_marker(payload)
    if existing_marker and not _analysis_push_force_enabled():
        return {
            "feishu_push": {
                "enabled": True,
                "skipped": True,
                "reason": "duplicate_analysis_window",
                "message_id": str(existing_marker.get("message_id") or ""),
                "pushed_at": str(existing_marker.get("pushed_at") or ""),
            }
        }
    files = payload.get("analysis_report_files") if isinstance(payload.get("analysis_report_files"), dict) else {}
    tenant_token = _feishu_get_tenant_access_token()
    receive_id_type, receive_id = _feishu_receive_target()
    push_mode = "interactive"
    fallback_reason = ""
    try:
        message = _feishu_send_interactive_message(
            tenant_token,
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            card=_analysis_feishu_card(payload),
        )
    except Exception as exc:
        push_mode = "text"
        fallback_reason = str(exc).strip()
        message = _feishu_send_text_message(
            tenant_token,
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            text=_analysis_feishu_message_text(payload),
        )
    message_id = str(message.get("message_id") or "")
    if message_id:
        _write_analysis_push_marker(payload, message_id=message_id, mode=push_mode)
    return {
        "feishu_push": {
            "enabled": True,
            "mode": push_mode,
            "receive_id_type": receive_id_type,
            "receive_id": receive_id,
            "message_id": message_id,
            "fallback_reason": fallback_reason,
            "deleted_local_reports": _delete_report_file_after_push(files),
        }
    }


def _maybe_push_feishu_test_report(payload: dict[str, object]) -> dict[str, object]:
    if not _feishu_test_push_enabled():
        return {}
    mode = str(payload.get("mode") or "").strip()
    if mode == "cleanup_daily_artifacts":
        return {}
    if mode == "local_video" and not _feishu_local_video_push_enabled():
        return {}
    if mode == "batch_drama":
        # 短剧 loop 改为仅保留本地/归档报告，不再向飞书推送单轮批量发布报告，
        # 避免白天/夜间多线路运行时持续刷屏。
        return {
            "test_feishu_push": {
                "enabled": False,
                "skipped": True,
                "reason": "batch_drama_push_disabled",
            }
        }
    if not isinstance(payload.get("test_report_files"), dict):
        return {}
    files = payload.get("test_report_files") if isinstance(payload.get("test_report_files"), dict) else {}
    tenant_token = _feishu_get_tenant_access_token()
    receive_id_type, receive_id = _feishu_receive_target()
    push_mode = "interactive"
    fallback_reason = ""
    try:
        message = _feishu_send_interactive_message(
            tenant_token,
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            card=_test_feishu_card(payload),
        )
    except Exception as exc:
        push_mode = "text"
        fallback_reason = str(exc).strip()
        message = _feishu_send_text_message(
            tenant_token,
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            text=_test_feishu_message_text(payload),
        )
    return {
        "test_feishu_push": {
            "enabled": True,
            "mode": push_mode,
            "receive_id_type": receive_id_type,
            "receive_id": receive_id,
            "message_id": str(message.get("message_id") or ""),
            "fallback_reason": fallback_reason,
            "deleted_local_reports": _delete_report_file_after_push(files),
        }
    }


def _unique_in_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _random_batch_platform_plan(count: int, platforms: list[str]) -> list[str]:
    available = _unique_in_order(platforms)
    if count <= 0 or not available:
        return []
    shuffled = random.sample(available, len(available))
    plan: list[str] = []
    while len(plan) < count:
        cycle = list(shuffled)
        random.shuffle(cycle)
        needed = count - len(plan)
        plan.extend(cycle[:needed])
    random.shuffle(plan)
    return plan


def _count_platform_plan(platform_plan: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for platform in platform_plan:
        counts[platform] = counts.get(platform, 0) + 1
    return counts


def _candidate_identity(item: dict) -> tuple[str, str, str]:
    return (
        str(item.get("serial_id") or ""),
        str(item.get("task_id") or ""),
        str(item.get("app_id") or ""),
    )


def _candidate_fetch_source(item: dict) -> str:
    return str(item.get("candidate_fetch_source") or "").strip()


def _candidate_source_mode(item: dict) -> str:
    return str(item.get("source_mode") or "").strip()


def _is_external_video_candidate(item: dict) -> bool:
    if _candidate_source_mode(item) == "external_video":
        return True
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    return str(raw.get("source_mode") or "").strip() == "external_video"


def _external_video_url(item: dict) -> str:
    value = str(item.get("external_video_url") or "").strip()
    if value:
        return value
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    return str(raw.get("external_video_url") or "").strip()


def _candidate_source_priority(item: dict) -> int:
    source = _candidate_fetch_source(item)
    if source == "realtime_rank_external":
        return 4
    if source == "realtime_rank_matched":
        return 3
    if source in {"task_api", ""}:
        return 2
    return 2


def _candidate_source_label(item: dict) -> str:
    source = _candidate_fetch_source(item)
    if source == "realtime_rank_external":
        return "实时榜外部素材"
    if source == "realtime_rank_matched":
        return "实时榜匹配"
    return "接口回退"


def _candidate_is_batch_eligible(item: dict) -> bool:
    if _is_external_video_candidate(item):
        return bool(str(item.get("serial_id") or "").strip() and str(item.get("app_id") or "").strip() and _external_video_url(item))
    return bool(str(item.get("serial_id") or "").strip() and str(item.get("app_id") or "").strip() and str(item.get("task_id") or "").strip())


def _candidate_batch_keys(item: dict) -> set[str]:
    keys = set(candidate_history_keys(item))
    serial_id, task_id, app_id = _candidate_identity(item)
    if serial_id or task_id or app_id:
        keys.add(f"identity:{serial_id}|{task_id}|{app_id}")
    return {key for key in keys if str(key).strip()}


def _append_unique_candidates(
    selected: list[dict],
    pool: list[dict],
    *,
    used_identities: set[tuple[str, str, str]],
    used_batch_keys: set[str],
) -> None:
    for candidate in pool:
        identity = _candidate_identity(candidate)
        batch_keys = _candidate_batch_keys(candidate)
        if identity in used_identities:
            continue
        if batch_keys and batch_keys & used_batch_keys:
            continue
        used_identities.add(identity)
        used_batch_keys.update(batch_keys)
        selected.append(candidate)


def _group_candidates_by_source_platform(candidates: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in candidates:
        platform = str(item.get("candidate_source_platform") or item.get("app_id") or "").strip()
        if not platform:
            continue
        grouped.setdefault(platform, []).append(item)
    return grouped


def _candidate_source_platform(item: dict) -> str:
    return str(item.get("candidate_source_platform") or item.get("app_id") or "").strip()


def _count_selected_platforms(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        platform = _candidate_source_platform(item)
        if not platform:
            continue
        counts[platform] = counts.get(platform, 0) + 1
    return counts


def _append_balanced_candidates(
    selected: list[dict],
    pool: list[dict],
    *,
    target_count: int,
    platform_targets: dict[str, int],
    used_identities: set[tuple[str, str, str]],
    used_batch_keys: set[str],
) -> None:
    if len(selected) >= target_count or not pool:
        return

    grouped = _group_candidates_by_source_platform(pool)
    for rows in grouped.values():
        rows.sort(
            key=lambda item: (
                float(item.get("candidate_final_score") or 0.0),
                _candidate_source_priority(item),
                float(item.get("share_rate") or 0.0),
                str(item.get("publish_at") or ""),
                str(item.get("serial_id") or ""),
            ),
            reverse=True,
        )

    while len(selected) < target_count:
        active_platforms = [platform for platform, rows in grouped.items() if rows]
        if not active_platforms:
            break

        selected_counts = _count_selected_platforms(selected)
        ordered_platforms = sorted(
            active_platforms,
            key=lambda platform: (
                0 if selected_counts.get(platform, 0) < int(platform_targets.get(platform, 0) or 0) else 1,
                -(int(platform_targets.get(platform, 0) or 0) - selected_counts.get(platform, 0)),
                selected_counts.get(platform, 0),
                -float((grouped.get(platform) or [{}])[0].get("candidate_final_score") or 0.0),
                platform,
            ),
        )

        picked = False
        for platform in ordered_platforms:
            rows = grouped.get(platform) or []
            while rows:
                candidate = _pick_light_random_candidate(rows)
                if candidate is None:
                    break
                rows.remove(candidate)
                identity = _candidate_identity(candidate)
                batch_keys = _candidate_batch_keys(candidate)
                if identity in used_identities:
                    continue
                if batch_keys and batch_keys & used_batch_keys:
                    continue
                used_identities.add(identity)
                used_batch_keys.update(batch_keys)
                selected.append(candidate)
                picked = True
                break
            if picked:
                break

        if not picked:
            break


def _candidate_observed_picks(db: FlywheelSQLite, item: dict) -> int:
    variant_serial_ids = item.get("candidate_variant_serial_ids")
    if isinstance(variant_serial_ids, list) and variant_serial_ids:
        return db.count_drama_picks_any(variant_serial_ids)
    return db.count_drama_picks(item.get("serial_id"))


def _batch_source_reserve_target(requested_count: int) -> int:
    requested = max(1, int(requested_count or 0))
    reserve = max(BATCH_PLAYABLE_SOURCE_BUFFER, min(12, max(4, requested)))
    return requested + reserve


def _score_batch_candidates(candidates: list[dict], *, db: FlywheelSQLite, config) -> list[dict]:
    if not candidates:
        return []
    total_rounds = db.count_rounds()
    scored_rows: list[dict] = []
    for item in candidates:
        normalized = dict(item)
        observed_picks = _candidate_observed_picks(db, normalized)
        score_breakdown = score_candidate(
            normalized,
            pool=candidates,
            observed_picks=observed_picks,
            total_rounds=total_rounds,
            weights=config.scoring_weights,
        )
        normalized["candidate_final_score"] = float(score_breakdown.get("final_score") or 0.0)
        normalized["candidate_score_breakdown"] = score_breakdown
        normalized["candidate_observed_picks"] = observed_picks
        scored_rows.append(normalized)
    scored_rows.sort(
        key=lambda item: (
            float(item.get("candidate_final_score") or 0.0),
            _candidate_source_priority(item),
            float(item.get("share_rate") or 0.0),
            str(item.get("publish_at") or ""),
            str(item.get("serial_id") or ""),
        ),
        reverse=True,
    )
    return scored_rows


def _pick_light_random_candidate(candidates: list[dict], *, top_window: int = 3) -> dict | None:
    if not candidates:
        return None
    window = candidates[: max(1, min(int(top_window), len(candidates)))]
    if len(window) == 1:
        return window[0]
    weights: list[float] = []
    for index, item in enumerate(window):
        base = float(item.get("candidate_final_score") or 0.0)
        source_priority = _candidate_source_priority(item)
        source_bonus = {4: 0.12, 3: 0.06, 2: 0.02, 1: 0.01}.get(source_priority, 0.0)
        rank_bias = max(0.05, 0.18 - index * 0.04)
        weights.append(max(0.01, base + source_bonus + rank_bias))
    return random.choices(window, weights=weights, k=1)[0]


def schema_path() -> Path:
    return Path(__file__).resolve().parent / "flywheel" / "db" / "schema.sql"


def ensure_runtime_dirs(config) -> None:
    for path in (
        Path(config.database_path).parent,
        Path(config.logs_dir),
        Path(config.source_dir),
        Path(config.clipped_dir),
        Path(config.covers_dir),
    ):
        path.mkdir(parents=True, exist_ok=True)


def _emit_stderr_line(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _start_stage_heartbeat(stage_name: str, *, detail: str = "", interval: int = HEARTBEAT_INTERVAL_SECONDS):
    started_at = time.perf_counter()
    prefix = f"[heartbeat] {stage_name}"
    opening = prefix if not detail else f"{prefix}: {detail}"
    _emit_stderr_line(opening)

    stop_event = threading.Event()

    def _runner() -> None:
        while not stop_event.wait(max(1, interval)):
            elapsed = format_seconds(time.perf_counter() - started_at)
            _emit_stderr_line(f"{prefix}: 仍在执行，已持续 {elapsed}")

    thread = threading.Thread(target=_runner, name=f"barry-video-{stage_name}", daemon=True)
    thread.start()
    return stop_event, thread, started_at


def _stop_stage_heartbeat(stage_name: str, stop_event, thread, started_at: float) -> None:
    stop_event.set()
    thread.join(timeout=0.2)
    elapsed = format_seconds(time.perf_counter() - started_at)
    _emit_stderr_line(f"[heartbeat] {stage_name}: 已完成，耗时 {elapsed}")


def cmd_init_db(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    ensure_runtime_dirs(config)
    db = FlywheelSQLite(Path(config.database_path))
    db.init_schema(schema_path())
    print(
        json.dumps(
            {
                "status": "ok",
                "database": str(config.database_path),
                "logs_dir": str(config.logs_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _round_payload_with_summary(result) -> dict[str, object]:
    report_zh = build_round_report_zh(
        round_id=result.round_id,
        status=result.status,
        stages=result.stages,
        live_refresh=False,
    )
    return {
        "status": result.status,
        "mode": "run_round",
        "round_id": result.round_id,
        "stages": result.stages,
        "report_zh": report_zh,
        "user_summary_zh": build_round_user_summary_zh(report_zh),
    }


def _test_summary_dir() -> Path:
    configured = str(os.getenv("BARRY_VIDEO_TEST_SUMMARY_DIR") or DEFAULT_TEST_SUMMARY_DIR).strip()
    return Path(configured).expanduser()


def _analysis_summary_dir() -> Path:
    configured = str(os.getenv("BARRY_VIDEO_ANALYSIS_SUMMARY_DIR") or DEFAULT_ANALYSIS_SUMMARY_DIR).strip()
    return Path(configured).expanduser()


def _analysis_push_marker_dir() -> Path:
    return _analysis_summary_dir() / ".push-state"


def _analysis_push_force_enabled() -> bool:
    return _truthy_env("BARRY_FEISHU_ANALYSIS_FORCE_PUSH")


def _analysis_push_marker_path(payload: dict[str, object]) -> Path:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    window = str(report.get("统计窗口") or "").strip()
    platform = str(report.get("目标平台") or "全部平台").strip() or "全部平台"
    env_key = str(API_ENV or "test").strip().lower() or "test"
    raw_key = f"{env_key}|{platform}|{window}"
    marker_name = hashlib.md5(raw_key.encode("utf-8")).hexdigest() + ".json"
    return _analysis_push_marker_dir() / marker_name


def _load_analysis_push_marker(payload: dict[str, object]) -> dict[str, object]:
    marker = _analysis_push_marker_path(payload)
    if not marker.exists() or not marker.is_file():
        return {}
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_analysis_push_marker(payload: dict[str, object], *, message_id: str, mode: str) -> None:
    marker = _analysis_push_marker_path(payload)
    marker.parent.mkdir(parents=True, exist_ok=True)
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    marker.write_text(
        json.dumps(
            {
                "mode": mode,
                "message_id": str(message_id or ""),
                "pushed_at": datetime.now().isoformat(timespec="seconds"),
                "platform": str(report.get("目标平台") or "全部平台"),
                "window": str(report.get("统计窗口") or ""),
                "environment": str(API_ENV or "test"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _safe_report_slug(value: str) -> str:
    raw = str(value or "").strip().lower()
    normalized = "".join(ch if ch.isalnum() else "_" for ch in raw)
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized or "report"


def _compact_error_text(value: str, *, max_length: int = 80) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split())
    lowered = text.lower()
    if "504" in lowered or "gateway time-out" in lowered or "gateway timeout" in lowered:
        return "接口 504 超时"
    if "timeout" in lowered or "timed out" in lowered or "超时" in text:
        return "请求超时"
    if "cannot publish reel" in lowered or "账号不能发布reel" in lowered or "账号不能发布 reel" in lowered:
        return "账号不支持 Reel"
    if len(text) > max_length:
        return text[: max(1, max_length - 1)].rstrip() + "..."
    return text or "未说明"


def _report_title_zh(payload: dict[str, object]) -> str:
    mode = str(payload.get("mode") or payload.get("执行模式") or "run")
    status = str(payload.get("status") or "")
    mode_map = {
        "batch_drama": "批量短剧测试总结",
        "local_video": "本地视频测试总结",
        "retry_failed_publish": "失败发布重试测试总结",
        "run_round": "飞轮单轮测试总结",
        "publish_analysis_daily": "发布数据分析日报",
        "discard_failed_publish_output": "失败成片清理记录",
        "show_failed_publish_paths": "失败成片路径记录",
    }
    title = mode_map.get(mode, "测试总结")
    if status:
        return f"{title}（{status}）"
    return title


def _report_daily_title_zh(payload: dict[str, object]) -> str:
    mode = str(payload.get("mode") or payload.get("执行模式") or "run")
    mode_map = {
        "batch_drama": "短剧批量发布报告",
        "local_video": "本地视频剪辑发布报告",
        "retry_failed_publish": "失败发布重试报告",
        "run_round": "飞轮单轮测试报告",
        "publish_analysis_daily": "发布数据分析日报",
        "discard_failed_publish_output": "失败成片清理记录",
        "show_failed_publish_paths": "失败成片路径记录",
        "show_round": "轮次测试报告",
    }
    return mode_map.get(mode, "测试报告")


def _report_filename_prefix_zh(payload: dict[str, object]) -> str:
    mode = str(payload.get("mode") or payload.get("执行模式") or "run")
    mode_map = {
        "batch_drama": "批量发布测试报告",
        "local_video": "本地视频测试报告",
        "retry_failed_publish": "失败重试测试报告",
        "run_round": "飞轮单轮测试报告",
        "publish_analysis_daily": "发布数据分析日报",
        "discard_failed_publish_output": "失败成片清理记录",
        "show_failed_publish_paths": "失败成片路径记录",
        "show_round": "轮次测试报告",
    }
    return mode_map.get(mode, "测试报告")


def _report_environment_zh() -> str:
    return "正式环境" if str(API_ENV or "").strip().lower() in {"prod", "production"} else "测试环境"


def _markdown_escape(value: object) -> str:
    text = ("" if value is None else str(value)).replace("\n", "<br>")
    return text.replace("|", "\\|")


def _markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    if not rows:
        return []
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        normalized = list(row[: len(headers)])
        if len(normalized) < len(headers):
            normalized.extend("" for _ in range(len(headers) - len(normalized)))
        lines.append("| " + " | ".join(_markdown_escape(cell) for cell in normalized) + " |")
    return lines


def _section_lines(title: str, lines: list[str]) -> list[str]:
    if not any(str(line or "").strip() for line in lines):
        return []
    return ["", f"## {title}", "", *[line for line in lines if line is not None]]


def _reason_counter_rows(reports: list[dict[str, object]]) -> list[list[object]]:
    counts: dict[str, int] = {}
    for report in reports:
        reason = str(report.get("失败原因") or report.get("错误") or "").strip() or "未提供"
        counts[reason] = counts.get(reason, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [[index + 1, reason, count] for index, (reason, count) in enumerate(ordered)]


def _count_report_success_items(report: dict[str, object]) -> int:
    success_reports = report.get("发布成功视频") if isinstance(report.get("发布成功视频"), list) else []
    return len(success_reports)


def _report_success_rate_text(success: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{(success / total * 100):.1f}%"


def _top_reason_text(report: dict[str, object]) -> str:
    failed_reports = report.get("发布失败任务") if isinstance(report.get("发布失败任务"), list) else []
    if not failed_reports:
        return "暂无明显失败集中点"
    reasons = _reason_counter_rows(failed_reports)
    if not reasons:
        return "暂无明显失败集中点"
    top = reasons[0]
    reason = str(top[1] or "").strip() or "未提供"
    count = int(top[2] or 0)
    if count <= 0:
        return "暂无明显失败集中点"
    return f"{reason}（{count} 条）"


def _top_theater_text(report: dict[str, object]) -> str:
    theater_counts = report.get("剧场分布") if isinstance(report.get("剧场分布"), dict) else {}
    if not theater_counts:
        return "暂无剧场分布"
    ordered = sorted(theater_counts.items(), key=lambda item: (-int(item[1] or 0), str(item[0])))
    theater, count = ordered[0]
    return f"{theater}（{count} 条）"


def _report_conclusion_lines(report: dict[str, object]) -> list[str]:
    total = int(report.get("请求数量") or report.get("计划数量") or 0)
    unique_playable = int(report.get("可用唯一短剧数") or 0)
    reuse_filled = int(report.get("复用补量数") or 0)
    if "仅规划" in str(report.get("执行模式") or ""):
        passed = int((report.get("安全门槛") or {}).get("通过数") or 0) if isinstance(report.get("安全门槛"), dict) else 0
        rejected = int((report.get("安全门槛") or {}).get("拦截数") or 0) if isinstance(report.get("安全门槛"), dict) else 0
        replaced = int((report.get("安全门槛") or {}).get("补位成功数") or 0) if isinstance(report.get("安全门槛"), dict) else 0
        lines = [
            f"本轮完成了 {int(report.get('计划数量') or 0)} 条任务规划，尚未进入剪辑发布。",
            f"安全门槛通过 {passed} 条，拦截 {rejected} 条，补位成功 {replaced} 条。",
            f"候选剧场主要集中在 {_top_theater_text(report)}。",
        ]
        if reuse_filled > 0:
            lines.insert(1, f"唯一可用短剧 {unique_playable} 部，不足部分已通过复用补量 {reuse_filled} 条。")
        return lines

    success = int(report.get("发布成功数") or _count_report_success_items(report) or 0)
    failed_reports = report.get("发布失败任务") if isinstance(report.get("发布失败任务"), list) else []
    failed = int(report.get("失败数") or len(failed_reports) or 0)
    processing = int(report.get("发布处理中数") or 0)
    safety_gate = report.get("安全门槛") if isinstance(report.get("安全门槛"), dict) else {}
    replaced = int(safety_gate.get("补位成功数") or 0)
    rejected = int(safety_gate.get("拦截数") or 0)
    lines = [
        f"本轮共执行 {total} 条任务，成功 {success} 条，失败 {failed} 条，处理中 {processing} 条，成功率 {_report_success_rate_text(success, total)}。",
        f"安全门槛拦截 {rejected} 条，自动补位成功 {replaced} 条。",
        f"剧场主要集中在 {_top_theater_text(report)}。",
        f"主要失败原因是 {_top_reason_text(report)}。",
    ]
    if reuse_filled > 0:
        lines.insert(1, f"唯一可用短剧 {unique_playable} 部，不足部分已通过复用补量 {reuse_filled} 条。")
    return lines

def _batch_narrative_block(report: dict[str, object]) -> list[str]:
    lines = _report_conclusion_lines(report)
    return [f"- {line}" for line in lines if str(line or "").strip()]


def _report_run_metadata_lines(payload: dict[str, object], report: dict[str, object], generated_at: str) -> list[str]:
    lines = [
        f"**执行时间**: {generated_at}",
        f"**环境**: {_report_environment_zh()}",
    ]
    target_platform = str(report.get("目标平台") or report.get("发布平台") or "")
    if target_platform:
        lines.append(f"**目标平台**: {target_platform}")
    return lines


def _batch_overview_rows(report: dict[str, object]) -> list[list[object]]:
    safety_gate = report.get("安全门槛") if isinstance(report.get("安全门槛"), dict) else {}
    return [
        ["请求数量", report.get("请求数量") or 0],
        ["计划数量", report.get("计划数量") or 0],
        ["可用唯一短剧数", report.get("可用唯一短剧数") or 0],
        ["复用补量数", report.get("复用补量数") or 0],
        ["剪辑成功数", report.get("剪辑成功数") or 0],
        ["发布提交数", report.get("发布提交数") or 0],
        ["发布成功数", report.get("发布成功数") or 0],
        ["发布处理中数", report.get("发布处理中数") or 0],
        ["失败数", report.get("失败数") or 0],
        ["安全门槛通过数", safety_gate.get("通过数") or 0],
        ["安全门槛拦截数", safety_gate.get("拦截数") or 0],
        ["安全门槛补位成功数", safety_gate.get("补位成功数") or 0],
        ["安全门槛补位缺口数", safety_gate.get("补位缺口数") or 0],
    ]


def _timing_rows(report: dict[str, object]) -> list[list[object]]:
    timings = report.get("阶段耗时") if isinstance(report.get("阶段耗时"), dict) else {}
    return [[stage, duration] for stage, duration in timings.items()]


def _theater_rows(report: dict[str, object]) -> list[list[object]]:
    theater_counts = report.get("剧场分布") if isinstance(report.get("剧场分布"), dict) else {}
    return [[theater, count] for theater, count in theater_counts.items()]


def _account_result_rows(report: dict[str, object]) -> list[list[object]]:
    detail_reports = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
    rows: list[list[object]] = []
    for item in sorted(detail_reports, key=lambda value: int(value.get("序号") or 0)):
        rows.append(
            [
                item.get("序号"),
                item.get("账号"),
                item.get("平台"),
                item.get("短剧"),
                item.get("剧场"),
                item.get("语言"),
                f"第{item.get('集数')}集" if int(item.get("集数") or 0) > 0 else "",
                item.get("剪辑手法"),
                item.get("去重手法"),
                item.get("视频时长"),
                item.get("发布情况"),
                item.get("失败原因") or item.get("错误") or "",
            ]
        )
    return rows


def _published_rows(report: dict[str, object]) -> list[list[object]]:
    success_reports = report.get("发布成功视频") if isinstance(report.get("发布成功视频"), list) else []
    rows: list[list[object]] = []
    for item in success_reports:
        rows.append(
            [
                item.get("账号"),
                item.get("平台"),
                item.get("短剧"),
                item.get("剧场"),
                item.get("语言"),
                f"第{item.get('集数')}集" if int(item.get("集数") or 0) > 0 else "",
                item.get("剪辑手法"),
                item.get("去重手法"),
                item.get("视频时长"),
                item.get("视频分辨率"),
                item.get("发布时间"),
                item.get("播放量") or 0,
                item.get("点赞数") or 0,
                item.get("评论数") or 0,
                item.get("分享数") or 0,
            ]
        )
    return rows


def _safety_reject_lines(report: dict[str, object]) -> list[str]:
    safety_gate = report.get("安全门槛") if isinstance(report.get("安全门槛"), dict) else {}
    rejected_preview = safety_gate.get("拦截明细") if isinstance(safety_gate.get("拦截明细"), list) else []
    if not rejected_preview:
        rejected_preview = safety_gate.get("拦截预览") if isinstance(safety_gate.get("拦截预览"), list) else []
    lines: list[str] = []
    for item in rejected_preview[:10]:
        if not isinstance(item, dict):
            continue
        drama = str(item.get("短剧") or "").strip()
        theater = str(item.get("剧场") or "").strip()
        episode = int(item.get("集数") or 0)
        reason = str(item.get("原因") or "").strip()
        reject_type = str(item.get("类型") or "").strip()
        replace_result = str(item.get("补位结果") or "").strip()
        parts = [reject_type, f"《{drama}》" if drama else "", theater, f"第{episode}集" if episode > 0 else "", reason, replace_result]
        line = " | ".join(part for part in parts if part)
        if line:
            lines.append(f"- {line}")
    return lines


def _realtime_source_usage_rows(report: dict[str, object]) -> list[list[object]]:
    detail_reports = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
    rows: list[list[object]] = []
    for item in sorted(detail_reports, key=lambda value: int(value.get("序号") or 0)):
        if not isinstance(item, dict):
            continue
        source_label = str(item.get("候选来源") or "").strip()
        if not source_label.startswith("实时榜"):
            continue
        rows.append(
            [
                item.get("序号"),
                item.get("账号"),
                item.get("短剧"),
                source_label,
                item.get("剧场"),
                f"第{item.get('集数')}集" if int(item.get("集数") or 0) > 0 else "",
                item.get("发布情况"),
            ]
        )
    return rows


def _realtime_source_summary_lines(report: dict[str, object]) -> list[str]:
    detail_reports = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
    external_unique = int(report.get("实时榜外部素材数") or 0)
    external_slots = int(report.get("实时榜外部素材填充槽位数") or 0)
    matched_count = 0
    external_count = 0
    for item in detail_reports:
        if not isinstance(item, dict):
            continue
        source_label = str(item.get("候选来源") or "").strip()
        if source_label == "实时榜匹配":
            matched_count += 1
        elif source_label == "实时榜外部素材":
            external_count += 1
    if external_unique <= 0 and external_slots <= 0 and matched_count <= 0 and external_count <= 0:
        return ["本轮未使用实时剧目榜素材。"]
    lines = [
        f"本轮使用实时剧目榜相关任务 {matched_count + external_count} 条，其中实时榜匹配北斗剧库 {matched_count} 条，实时榜外部素材 {external_count} 条。"
    ]
    if external_unique > 0 or external_slots > 0:
        lines.append(f"实时榜外部素材命中 {external_unique} 个素材，共填充 {external_slots} 个账号槽位。")
    return lines


def _report_batch_markdown(payload: dict[str, object], report: dict[str, object], generated_at: str) -> str:
    total = int(report.get("请求数量") or 0)
    success_count = int(report.get("发布成功数") or _count_report_success_items(report) or 0)
    failed_reports = report.get("发布失败任务") if isinstance(report.get("发布失败任务"), list) else []
    processing_count = int(report.get("发布处理中数") or 0)
    theater_counts = report.get("剧场分布") if isinstance(report.get("剧场分布"), dict) else {}
    unsupported_accounts = [
        str(item.get("账号") or "").strip()
        for item in failed_reports
        if str(item.get("是否可自动重试") or "") == "否"
        and str(item.get("账号") or "").strip()
    ]
    material_timeout_count = sum(
        1
        for item in failed_reports
        if any(
            token in str(item.get("失败原因") or item.get("错误") or "")
            for token in ("素材超时", "未提交", "文件不存在", "暂无可下载视频")
        )
    )
    detail_reports = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
    realtime_source_lines = _realtime_source_summary_lines(report)
    realtime_source_rows = _markdown_table(
        ["序号", "账号", "短剧", "素材来源", "剧场", "集数", "发布状态"],
        _realtime_source_usage_rows(report),
    )
    realtime_matched_count = sum(
        1 for item in detail_reports if isinstance(item, dict) and str(item.get("候选来源") or "").strip() == "实时榜匹配"
    )
    realtime_external_count = sum(
        1 for item in detail_reports if isinstance(item, dict) and str(item.get("候选来源") or "").strip() == "实时榜外部素材"
    )
    lines: list[str] = [
        "# 短剧批量发布报告",
        "",
        f"**生成时间**: {generated_at}",
        f"**目标平台**: {report.get('目标平台') or ''}",
        f"**环境**: {_report_environment_zh()}",
        f"**执行轮次**: 1 轮",
        "",
        "---",
        "",
        "## 总体概览",
        "",
        *_markdown_table(
            ["指标", "数值"],
            [
                ["目标发布数", f"{total} 条"],
                ["累计发布成功", f"{success_count} 条"],
                ["累计发布失败", f"{len(failed_reports)} 条"],
                ["累计素材超时/未提交", f"{material_timeout_count} 条"],
                ["实时榜匹配任务", f"{realtime_matched_count} 条"],
                ["实时榜外部素材任务", f"{realtime_external_count} 条"],
                ["实时榜外部素材命中", f"{report.get('实时榜外部素材数') or 0} 个素材"],
                ["实时榜外部素材填充槽位", f"{report.get('实时榜外部素材填充槽位数') or 0} 个账号槽位"],
                ["涉及账号总数", f"{len(report.get('任务明细') or [])} 个账号"],
                ["不支持 Reel 的账号", f"{len(unsupported_accounts)} 个（{_join_non_empty(unsupported_accounts, '、') or '无'}）"],
                ["发布处理中（待确认）", f"{processing_count} 条"],
            ],
        ),
        "",
        "## 实时榜素材使用情况",
        "",
        *[f"- {item}" for item in realtime_source_lines],
        "",
    ]
    if realtime_source_rows:
        lines.extend(realtime_source_rows)
        lines.append("")
    line_runs = report.get("线路汇总") if isinstance(report.get("线路汇总"), list) else []
    if line_runs:
        lines.extend([
            "## 线路汇总",
            "",
        ])
        line_rows = _markdown_table(
            ["线路", "账号池", "计划数", "成功", "失败", "未提交", "备注"],
            [
                [
                    item.get("线路") or item.get("line_label") or item.get("line_name") or "",
                    item.get("账号池") or item.get("pool_name") or "",
                    item.get("计划数") or item.get("requested_count") or 0,
                    item.get("成功数") or item.get("success_count") or 0,
                    item.get("失败数") or item.get("failed_count") or 0,
                    item.get("未提交数") or item.get("unsubmitted_count") or 0,
                    item.get("备注") or item.get("note") or "",
                ]
                for item in line_runs
                if isinstance(item, dict)
            ],
        )
        if line_rows:
            lines.extend(line_rows)
            lines.append("")
    lines.extend([
        "## 任务明细",
        "",
    ])
    detail_rows = _markdown_table(
        ["序号", "线路", "账号", "短剧", "素材来源", "剧场", "语言", "剪辑手法", "去重手法", "视频时长", "发布状态", "备注"],
        [
            [
                item.get("序号"),
                item.get("线路") or "-",
                item.get("账号"),
                item.get("短剧"),
                item.get("候选来源"),
                item.get("剧场"),
                item.get("语言"),
                item.get("剪辑手法"),
                item.get("去重手法"),
                item.get("视频时长"),
                item.get("发布情况"),
                item.get("失败原因") or item.get("错误") or "",
            ]
            for item in (report.get("任务明细") if isinstance(report.get("任务明细"), list) else [])
        ],
    )
    if detail_rows:
        lines.extend(detail_rows)
        lines.append("")

    safety_reject_rows = _markdown_table(
        ["类型", "原槽位", "短剧", "剧场", "集数", "原因", "补位结果"],
        [
            [
                item.get("类型") or "",
                item.get("原槽位") or "",
                item.get("短剧") or "",
                item.get("剧场") or "",
                item.get("集数") or "",
                item.get("原因") or "",
                item.get("补位结果") or "",
            ]
            for item in (
                ((report.get("安全门槛") or {}).get("拦截明细"))
                if isinstance(((report.get("安全门槛") or {}).get("拦截明细")), list)
                else []
            )
        ],
    )
    if safety_reject_rows:
        lines.extend(["## 安全门槛拦截明细", ""])
        lines.extend(safety_reject_rows)
        lines.append("")

    failed_rows = _markdown_table(
        ["失败原因", "次数"],
        [[reason, count] for _, reason, count in _reason_counter_rows(failed_reports)],
    )
    if failed_rows:
        lines.extend(["## 失败原因分析", "", *failed_rows, ""])

    if theater_counts:
        theater_rows = _markdown_table(
            ["剧场", "数量"],
            [[theater, count] for theater, count in theater_counts.items()],
        )
        lines.extend(["## 剧场分布", "", *theater_rows, ""])

    suggestions = _failed_publish_suggestions_zh(report)
    if suggestions:
        lines.extend(["## 建议", ""])
        lines.extend(f"- {item}" for item in suggestions)
        lines.append("")

    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def _analysis_metric_rows(items: list[dict[str, object]], *, limit: int = 20) -> list[list[object]]:
    rows: list[list[object]] = []
    for item in items[:limit]:
        rows.append(
            [
                item.get("名称"),
                item.get("帖子数"),
                item.get("播放量"),
                item.get("互动量"),
                item.get("互动率"),
                item.get("收益"),
                item.get("单条收益"),
                item.get("千次播放收益"),
            ]
        )
    return rows


def _analysis_overview_fields(summary: dict[str, object]) -> list[list[object]]:
    return [
        ["日期", summary.get("日期") or "-"],
        ["轮次", summary.get("轮次") or 0],
        ["模式", summary.get("模式") or "-"],
        ["当日发布视频总数", summary.get("当日发布视频总数") or 0],
        ["当日发布成功数", summary.get("当日发布成功数") or 0],
        ["任务数", summary.get("任务数") or 0],
        ["发布成功条数", summary.get("发布成功条数") or 0],
        ["发布失败条数", summary.get("发布失败条数") or 0],
        ["上传失败条数", summary.get("上传失败条数") or 0],
        ["覆盖账号数", summary.get("覆盖账号数") or 0],
        ["失败账号数", summary.get("失败账号数") or 0],
        ["发布失败账号数", summary.get("发布失败账号数") or 0],
        ["失败账号", summary.get("失败账号") or "-"],
        ["发布失败账号", summary.get("发布失败账号") or "-"],
        ["当日推广链接点击次数", summary.get("当日推广链接点击次数") or summary.get("推广链接点击次数") or 0],
        ["订单数", summary.get("订单数") or 0],
        ["订单金额", summary.get("订单金额") or 0],
        ["广告金额", summary.get("广告金额") or 0],
        ["分佣金额", summary.get("分佣金额") or 0],
        ["总收益", summary.get("总收益") or 0],
        ["总播放量", summary.get("总播放量") or 0],
        ["点赞数", summary.get("点赞数") or 0],
        ["评论数", summary.get("评论数") or 0],
        ["分享数", summary.get("分享数") or 0],
        ["总互动量", summary.get("总互动量") or 0],
        ["整体互动率", summary.get("整体互动率") or "0.00%"],
        ["千次播放收益", summary.get("千次播放收益") or 0],
        ["剪辑下载均耗", summary.get("剪辑下载均耗") or "-"],
        ["原视频均长", summary.get("原视频均长") or "-"],
        ["原视频时长缺失数", summary.get("原视频时长缺失数") or "-"],
        ["输出片段均长", summary.get("输出片段均长") or "-"],
        ["成片探测均长", summary.get("成片探测均长") or "-"],
        ["剪辑工具分布", summary.get("剪辑工具分布") or "-"],
        ["剪辑方式分布", summary.get("剪辑方式分布") or "-"],
        ["去重方式分布", summary.get("去重方式分布") or "-"],
        ["剧场/短剧匹配率", summary.get("剧场短剧匹配率") or "0.00%"],
        ["接口总条数", summary.get("接口总条数") or 0],
        ["实际分析条数", summary.get("实际分析条数") or 0],
        ["覆盖平台数", summary.get("覆盖平台数") or 0],
        ["平均单条播放", summary.get("平均单条播放") or 0],
        ["平均单条收益", summary.get("平均单条收益") or 0],
    ]


def _analysis_failure_reason_summary(rows: list[dict[str, object]], *, limit: int = 3) -> str:
    parts: list[str] = []
    for item in rows[:limit]:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("失败原因") or item.get("原因") or item.get("名称") or "").strip() or "未分类"
        count = _safe_int(item.get("数量") or item.get("次数"))
        if count > 0:
            parts.append(f"{reason} {count} 次")
        else:
            parts.append(reason)
    return "、".join(parts)


def _analysis_failure_accounts_summary(rows: list[dict[str, object]], *, limit: int = 3) -> str:
    accounts: list[str] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        account = str(item.get("账号") or "").strip()
        if not account or account == "-" or account in accounts:
            continue
        accounts.append(account)
        if len(accounts) >= limit:
            break
    if not accounts:
        return ""
    return "、".join(accounts)


def _analysis_failure_summary_lines(
    drama_overview: dict[str, object],
    drama_reason_rows: list[dict[str, object]],
    drama_failure_details: list[dict[str, object]],
    novel_overview: dict[str, object],
    novel_reason_rows: list[dict[str, object]],
    novel_failure_details: list[dict[str, object]],
) -> list[str]:
    lines: list[str] = []
    for label, overview, reason_rows, failure_details in [
        ("短剧", drama_overview, drama_reason_rows, drama_failure_details),
        ("小说", novel_overview, novel_reason_rows, novel_failure_details),
    ]:
        publish_failed = _safe_int(overview.get("发布失败条数"))
        upload_failed = _safe_int(overview.get("上传失败条数"))
        failed_accounts = _safe_int(overview.get("失败账号数"))
        publish_failed_accounts = _safe_int(overview.get("发布失败账号数"))
        if publish_failed <= 0 and upload_failed <= 0 and not reason_rows and not failure_details:
            continue
        line = (
            f"{label}侧有失败情况：发布失败 {publish_failed} 条，上传失败 {upload_failed} 条，"
            f"涉及失败账号 {failed_accounts} 个，其中发布失败账号 {publish_failed_accounts} 个。"
        )
        reason_summary = _analysis_failure_reason_summary(reason_rows)
        if reason_summary:
            line += f" 主要原因：{reason_summary}。"
        account_summary = _analysis_failure_accounts_summary(failure_details)
        if account_summary:
            line += f" 示例账号：{account_summary}。"
        lines.append(line)
    return lines


def _analysis_task_overview_fields(summary: dict[str, object]) -> list[list[object]]:
    return [
        ["任务数", summary.get("任务数") or 0],
        ["有点击任务数", summary.get("有点击任务数") or 0],
        ["点击数", summary.get("点击数") or 0],
        ["订单数", summary.get("订单数") or 0],
        ["订单金额", summary.get("订单金额") or 0],
        ["广告金额", summary.get("广告金额") or 0],
        ["分佣金额", summary.get("分佣金额") or 0],
        ["有数据任务数", summary.get("有数据任务数") or 0],
    ]


def _analysis_execution_fields(summary: dict[str, object]) -> list[list[object]]:
    return [
        ["日期", summary.get("日期") or "-"],
        ["轮次", summary.get("轮次") or 0],
        ["模式", summary.get("模式") or "-"],
        ["任务数", summary.get("任务数") or 0],
        ["发布成功条数", summary.get("发布成功条数") or 0],
        ["发布失败条数", summary.get("发布失败条数") or 0],
        ["上传失败条数", summary.get("上传失败条数") or 0],
        ["失败账号数", summary.get("失败账号数") or 0],
        ["发布失败账号数", summary.get("发布失败账号数") or 0],
        ["剪辑下载均耗", summary.get("剪辑下载均耗") or "-"],
        ["原视频均长", summary.get("原视频均长") or "-"],
        ["原视频时长缺失数", summary.get("原视频时长缺失数") or "-"],
        ["输出片段均长", summary.get("输出片段均长") or "-"],
        ["成片探测均长", summary.get("成片探测均长") or "-"],
        ["剪辑工具分布", summary.get("剪辑工具分布") or "-"],
        ["剪辑方式分布", summary.get("剪辑方式分布") or "-"],
        ["去重方式分布", summary.get("去重方式分布") or "-"],
        ["失败账号", summary.get("失败账号") or "-"],
        ["发布失败账号", summary.get("发布失败账号") or "-"],
    ]


def _analysis_compact_distribution(counter: dict[str, int], *, limit: int = 6) -> str:
    if not counter:
        return "-"
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return "｜".join(f"{name} {count}" for name, count in ordered[:limit])


def _analysis_distribution_rows(counter: dict[str, int], label: str) -> list[dict[str, object]]:
    return [
        {label: name, "数量": count}
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _analysis_join_accounts(accounts: set[str], *, limit: int = 8) -> str:
    if not accounts:
        return "-"
    ordered = sorted(account for account in accounts if str(account).strip())
    if len(ordered) <= limit:
        return "、".join(ordered)
    return "、".join(ordered[:limit]) + f" 等 {len(ordered)} 个"


def _analysis_seconds_text(value: object) -> str:
    seconds = _safe_float(value)
    if seconds <= 0:
        return "-"
    return format_seconds(int(round(seconds)))


def _analysis_avg_seconds_text(total_seconds: float, count: int) -> str:
    if total_seconds <= 0 or count <= 0:
        return "-"
    return format_seconds(int(round(total_seconds / max(1, count))))


def _analysis_round_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"round[_-]?(\d+)", path.stem, re.IGNORECASE)
    if match:
        return (int(match.group(1)), path.name)
    return (10**9, path.name)


def _analysis_state_dir_candidates(kind: str, report_day: str) -> list[Path]:
    root_dir = Path.cwd()
    if kind == "drama":
        env_root = str(os.getenv("BARRY_LOOP_STATE_ROOT") or "").strip()
        roots = [
            Path(env_root) if env_root else None,
            root_dir / "runtime" / "daily-loop",
            root_dir / "data" / "daily-loop",
        ]
    else:
        env_root = str(os.getenv("BARRY_NOVEL_LOOP_STATE_ROOT") or "").strip()
        roots = [
            Path(env_root) if env_root else None,
            root_dir / "runtime" / "novel-loop",
            root_dir / "runtime" / "novel-loop-local",
        ]
    day_dirs: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if root is None:
            continue
        day_dir = root / report_day
        key = str(day_dir)
        if key in seen:
            continue
        seen.add(key)
        day_dirs.append(day_dir)
    return day_dirs


def _analysis_load_round_payloads(report_day: str, kind: str) -> tuple[str, list[tuple[str, dict[str, object]]]]:
    for day_dir in _analysis_state_dir_candidates(kind, report_day):
        if not day_dir.exists() or not day_dir.is_dir():
            continue
        round_files = sorted(day_dir.glob("round*.json"), key=_analysis_round_sort_key)
        payloads: list[tuple[str, dict[str, object]]] = []
        for index, path in enumerate(round_files, start=1):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            match = re.search(r"round[_-]?(\d+)", path.stem, re.IGNORECASE)
            round_no = int(match.group(1)) if match else index
            payloads.append((f"第 {round_no} 轮", payload if isinstance(payload, dict) else {}))
        return str(day_dir), payloads
    return "", []


def _analysis_clean_failure_reason(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) > 120:
        return text[:117] + "..."
    return text


def _analysis_is_upload_failure(reason: str) -> bool:
    lowered = reason.lower()
    return any(
        token in lowered
        for token in [
            "上传",
            "upload",
            "file upload",
            "发布视频失败",
            "publish file",
        ]
    )


def _analysis_state_value(payload: dict[str, object], key: str, default: int = 0) -> int:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    return _safe_int(report.get(key) if isinstance(report, dict) else default) or default


def _summarize_drama_execution(report_day: str) -> dict[str, object]:
    state_dir, rounds = _analysis_load_round_payloads(report_day, "drama")
    task_count = 0
    success_count = 0
    publish_failed_count = 0
    upload_failed_count = 0
    clip_seconds_total = 0.0
    output_duration_values: list[float] = []
    failed_accounts: set[str] = set()
    publish_failed_accounts: set[str] = set()
    clip_tool_counter: dict[str, int] = {}
    cut_method_counter: dict[str, int] = {}
    dedup_counter: dict[str, int] = {}
    failure_reason_counter: dict[str, int] = {}
    failure_details: list[dict[str, object]] = []
    timing_rows: list[dict[str, object]] = []

    for round_label, payload in rounds:
        report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
        rows = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
        task_count += _safe_int(report.get("计划数量")) or len(rows)
        success_count += _safe_int(report.get("发布成功数"))
        clip_seconds = _safe_float((payload.get("timings") or {}).get("剪辑与下载")) if isinstance(payload.get("timings"), dict) else 0.0
        clip_seconds_total += clip_seconds
        timing_rows.append(
            {
                "轮次": round_label,
                "任务数": _safe_int(report.get("计划数量")) or len(rows),
                "剪辑下载耗时": _analysis_seconds_text(clip_seconds),
            }
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            clip_tool_counter["短剧智能剪辑"] = clip_tool_counter.get("短剧智能剪辑", 0) + 1
            cut_method = str(row.get("剪辑手法") or "").strip()
            if cut_method:
                cut_method_counter[cut_method] = cut_method_counter.get(cut_method, 0) + 1
            dedup_method = str(row.get("去重手法") or "").strip()
            if dedup_method:
                dedup_counter[dedup_method] = dedup_counter.get(dedup_method, 0) + 1
            duration_seconds = _safe_float(row.get("视频时长秒"))
            if duration_seconds > 0:
                output_duration_values.append(duration_seconds)
            publish_status = str(row.get("发布情况") or "").strip()
            reason = _analysis_clean_failure_reason(row.get("失败原因") or row.get("错误"))
            account = str(row.get("账号") or "").strip()
            drama = str(row.get("短剧") or "").strip()
            if publish_status == "发布失败":
                publish_failed_count += 1
                if account:
                    publish_failed_accounts.add(account)
            if publish_status in {"发布失败", "未提交"} or reason:
                if account:
                    failed_accounts.add(account)
                if reason:
                    failure_reason_counter[reason] = failure_reason_counter.get(reason, 0) + 1
                    if _analysis_is_upload_failure(reason):
                        upload_failed_count += 1
                failure_details.append(
                    {
                        "账号": account or "-",
                        "短剧": drama or "-",
                        "发布情况": publish_status or "-",
                        "失败原因": reason or "-",
                    }
                )

    avg_output = round(sum(output_duration_values) / len(output_duration_values), 2) if output_duration_values else 0.0
    overview = {
        "日期": report_day,
        "轮次": len(rounds),
        "模式": "短剧 loop",
        "任务数": task_count,
        "发布成功条数": success_count,
        "发布失败条数": publish_failed_count,
        "上传失败条数": upload_failed_count,
        "失败账号数": len(failed_accounts),
        "发布失败账号数": len(publish_failed_accounts),
        "失败账号": _analysis_join_accounts(failed_accounts),
        "发布失败账号": _analysis_join_accounts(publish_failed_accounts),
        "剪辑下载均耗": _analysis_avg_seconds_text(clip_seconds_total, task_count),
        "原视频均长": "-",
        "原视频时长缺失数": task_count if task_count > 0 else 0,
        "输出片段均长": _analysis_seconds_text(avg_output),
        "成片探测均长": _analysis_seconds_text(avg_output),
        "剪辑工具分布": _analysis_compact_distribution(clip_tool_counter),
        "剪辑方式分布": _analysis_compact_distribution(cut_method_counter),
        "去重方式分布": _analysis_compact_distribution(dedup_counter),
        "状态目录": state_dir or "-",
    }
    return {
        "overview": overview,
        "timing_rows": timing_rows,
        "failure_reason_rows": _analysis_distribution_rows(failure_reason_counter, "失败原因"),
        "failure_details": failure_details[:20],
    }


def _summarize_novel_execution(report_day: str) -> dict[str, object]:
    state_dir, rounds = _analysis_load_round_payloads(report_day, "novel")
    task_count = 0
    success_count = 0
    publish_failed_count = 0
    upload_failed_count = 0
    failed_accounts: set[str] = set()
    publish_failed_accounts: set[str] = set()
    tool_counter: dict[str, int] = {}
    method_counter: dict[str, int] = {}
    failure_reason_counter: dict[str, int] = {}
    failure_details: list[dict[str, object]] = []
    timing_rows: list[dict[str, object]] = []

    for round_label, payload in rounds:
        report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
        rows = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
        round_task_count = _safe_int(report.get("计划小说数")) or len(rows)
        task_count += round_task_count
        round_success = max(_safe_int(report.get("成功条数")), _safe_int(report.get("已发布")))
        success_count += round_success
        timing_rows.append(
            {
                "轮次": round_label,
                "任务数": round_task_count,
                "剪辑下载耗时": "-",
            }
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            generator = str(row.get("generator") or "").strip() or "未知工具"
            tool_counter[generator] = tool_counter.get(generator, 0) + 1
            method = str(row.get("generation_chain") or "").strip() or "未知链路"
            method_counter[method] = method_counter.get(method, 0) + 1
            status = str(row.get("status") or row.get("publish_status") or "").strip().lower()
            account = str(row.get("account") or "").strip()
            title = str(row.get("title") or "").strip()
            reason = _analysis_clean_failure_reason(row.get("failure_reason") or row.get("error"))
            if str(row.get("publish_status") or "").strip().lower() == "failed":
                publish_failed_count += 1
                if account:
                    publish_failed_accounts.add(account)
            if status == "failed" or reason:
                if account:
                    failed_accounts.add(account)
                if reason:
                    failure_reason_counter[reason] = failure_reason_counter.get(reason, 0) + 1
                    if _analysis_is_upload_failure(reason):
                        upload_failed_count += 1
                failure_details.append(
                    {
                        "账号": account or "-",
                        "短剧": title or "-",
                        "发布情况": status or "-",
                        "失败原因": reason or "-",
                    }
                )

    overview = {
        "日期": report_day,
        "轮次": len(rounds),
        "模式": "小说 loop",
        "任务数": task_count,
        "发布成功条数": success_count,
        "发布失败条数": publish_failed_count,
        "上传失败条数": upload_failed_count,
        "失败账号数": len(failed_accounts),
        "发布失败账号数": len(publish_failed_accounts),
        "失败账号": _analysis_join_accounts(failed_accounts),
        "发布失败账号": _analysis_join_accounts(publish_failed_accounts),
        "剪辑下载均耗": "-",
        "原视频均长": "-",
        "原视频时长缺失数": "-",
        "输出片段均长": "-",
        "成片探测均长": "-",
        "剪辑工具分布": _analysis_compact_distribution(tool_counter),
        "剪辑方式分布": _analysis_compact_distribution(method_counter),
        "去重方式分布": "-",
        "状态目录": state_dir or "-",
    }
    return {
        "overview": overview,
        "timing_rows": timing_rows,
        "failure_reason_rows": _analysis_distribution_rows(failure_reason_counter, "失败原因"),
        "failure_details": failure_details[:20],
    }


def _analysis_feishu_card(payload: dict[str, object]) -> dict[str, object]:
    return build_analysis_feishu_card(payload)


def _report_publish_analysis_markdown(payload: dict[str, object], report: dict[str, object], generated_at: str) -> str:
    summary = report.get("总体概览") if isinstance(report.get("总体概览"), dict) else {}
    drama_overview = report.get("短剧总体概览") if isinstance(report.get("短剧总体概览"), dict) else {}
    novel_overview = report.get("小说总体概览") if isinstance(report.get("小说总体概览"), dict) else {}
    drama_task_summary = report.get("短剧任务概览") if isinstance(report.get("短剧任务概览"), dict) else {}
    novel_task_summary = report.get("小说任务概览") if isinstance(report.get("小说任务概览"), dict) else {}
    account_rows = report.get("账号维度") if isinstance(report.get("账号维度"), list) else []
    platform_rows = report.get("平台维度") if isinstance(report.get("平台维度"), list) else []
    theater_rows = report.get("剧场维度") if isinstance(report.get("剧场维度"), list) else []
    drama_rows = report.get("短剧维度") if isinstance(report.get("短剧维度"), list) else []
    my_task_overview = report.get("我的短剧任务概览") if isinstance(report.get("我的短剧任务概览"), dict) else {}
    my_task_rows = report.get("我的短剧任务维度") if isinstance(report.get("我的短剧任务维度"), list) else []
    my_novel_task_overview = report.get("我的小说任务概览") if isinstance(report.get("我的小说任务概览"), dict) else {}
    my_novel_task_rows = report.get("我的小说任务维度") if isinstance(report.get("我的小说任务维度"), list) else []
    failure_summary = report.get("失败情况总结") if isinstance(report.get("失败情况总结"), list) else []
    anomaly_rows = report.get("异常账号") if isinstance(report.get("异常账号"), list) else []
    suggestions = report.get("建议") if isinstance(report.get("建议"), list) else []
    lines: list[str] = [
        "# 发布数据分析日报",
        "",
        f"**生成时间**: {generated_at}",
        f"**目标平台**: {report.get('目标平台') or '全部平台'}",
        f"**统计窗口**: {report.get('统计窗口') or ''}",
        f"**数据延迟说明**: {report.get('数据延迟说明') or '平台数据通常延迟 1-2 天'}",
        f"**环境**: {_report_environment_zh()}",
        "",
        "---",
        "",
        "## 总体概览",
        "",
        *_markdown_table(
            ["指标", "数值"],
            _analysis_overview_fields(summary),
        ),
        "",
    ]

    if drama_overview:
        lines.extend(
            [
                "## 短剧总体概览",
                "",
                *_markdown_table(["指标", "数值"], _analysis_overview_fields(drama_overview)),
                "",
            ]
        )

    if novel_overview:
        lines.extend(
            [
                "## 小说总体概览",
                "",
                *_markdown_table(["指标", "数值"], _analysis_overview_fields(novel_overview)),
                "",
            ]
        )

    overview_text = str(report.get("结论摘要") or "").strip()
    if overview_text:
        lines.extend(["## 结论摘要", "", f"- {overview_text}", ""])
    if failure_summary:
        lines.extend(["## 失败情况总结", ""])
        lines.extend(f"- {str(item).strip()}" for item in failure_summary if str(item).strip())
        lines.append("")

    drama_task_summary_table = _markdown_table(
        ["指标", "数值"],
        _analysis_task_overview_fields(drama_task_summary),
    )
    if drama_task_summary_table:
        lines.extend(["## 短剧任务概览", "", *drama_task_summary_table, ""])

    novel_task_summary_table = _markdown_table(
        ["指标", "数值"],
        _analysis_task_overview_fields(novel_task_summary),
    )
    if novel_task_summary_table:
        lines.extend(["## 小说任务概览", "", *novel_task_summary_table, ""])

    for title, rows in [
        ("账号维度", account_rows),
        ("平台维度", platform_rows),
        ("剧场维度", theater_rows),
        ("短剧维度", drama_rows),
    ]:
        table = _markdown_table(
            ["名称", "帖子数", "播放量", "互动量", "互动率", "收益", "单条收益", "千次播放收益"],
            _analysis_metric_rows(rows),
        )
        if table:
            lines.extend([f"## {title}", "", *table, ""])

    my_task_overview_table = _markdown_table(
        ["指标", "数值"],
        [
            ["任务总数", my_task_overview.get("任务总数") or 0],
            ["当前平台有数据任务数", my_task_overview.get("当前平台有数据任务数") or 0],
            ["有点击任务数", my_task_overview.get("有点击任务数") or 0],
            ["有订单任务数", my_task_overview.get("有订单任务数") or 0],
            ["当前平台累计推广链接点击次数", my_task_overview.get("当前平台累计点击") or 0],
            ["当前平台累计订单", my_task_overview.get("当前平台累计订单") or 0],
            ["当前平台累计充值金额", my_task_overview.get("当前平台累计充值金额") or 0],
            ["当前平台累计广告金额", my_task_overview.get("当前平台累计广告金额") or 0],
            ["当前平台累计分佣", my_task_overview.get("当前平台累计分佣") or 0],
        ],
    )
    if my_task_overview_table:
        lines.extend(["## 我的短剧任务概览", "", *my_task_overview_table, ""])

    my_task_table = _markdown_table(
        ["短剧", "剧场", "语言", "推广时间", "本平台点击", "本平台订单", "本平台广告金额", "本平台分佣", "总点击", "总订单", "总分佣"],
        [
            [
                item.get("短剧"),
                item.get("剧场"),
                item.get("语言"),
                item.get("推广时间"),
                item.get("本平台点击"),
                item.get("本平台订单"),
                item.get("本平台广告金额"),
                item.get("本平台分佣"),
                item.get("总点击"),
                item.get("总订单"),
                item.get("总分佣"),
            ]
            for item in my_task_rows
        ],
    )
    if my_task_table:
        lines.extend(["## 我的短剧任务维度", "", *my_task_table, ""])

    my_novel_task_overview_table = _markdown_table(
        ["指标", "数值"],
        [
            ["任务总数", my_novel_task_overview.get("任务总数") or 0],
            ["当前平台有数据任务数", my_novel_task_overview.get("当前平台有数据任务数") or 0],
            ["有点击任务数", my_novel_task_overview.get("有点击任务数") or 0],
            ["有订单任务数", my_novel_task_overview.get("有订单任务数") or 0],
            ["当前平台累计推广链接点击次数", my_novel_task_overview.get("当前平台累计点击") or 0],
            ["当前平台累计订单", my_novel_task_overview.get("当前平台累计订单") or 0],
            ["当前平台累计充值金额", my_novel_task_overview.get("当前平台累计充值金额") or 0],
            ["当前平台累计广告金额", my_novel_task_overview.get("当前平台累计广告金额") or 0],
            ["当前平台累计分佣", my_novel_task_overview.get("当前平台累计分佣") or 0],
        ],
    )
    if my_novel_task_overview_table:
        lines.extend(["## 我的小说任务概览", "", *my_novel_task_overview_table, ""])

    my_novel_task_table = _markdown_table(
        ["小说", "平台应用", "语言", "推广时间", "本平台点击", "本平台订单", "本平台广告金额", "本平台分佣", "总点击", "总订单", "总分佣"],
        [
            [
                item.get("小说"),
                item.get("平台应用"),
                item.get("语言"),
                item.get("推广时间"),
                item.get("本平台点击"),
                item.get("本平台订单"),
                item.get("本平台广告金额"),
                item.get("本平台分佣"),
                item.get("总点击"),
                item.get("总订单"),
                item.get("总分佣"),
            ]
            for item in my_novel_task_rows
        ],
    )
    if my_novel_task_table:
        lines.extend(["## 我的小说任务维度", "", *my_novel_task_table, ""])

    anomaly_table = _markdown_table(
        ["账号", "平台", "帖子数", "播放量", "收益", "说明"],
        [
            [
                item.get("账号"),
                item.get("平台"),
                item.get("帖子数"),
                item.get("播放量"),
                item.get("收益"),
                item.get("说明"),
            ]
            for item in anomaly_rows[:20]
        ],
    )
    if anomaly_table:
        lines.extend(["## 异常账号", "", *anomaly_table, ""])

    if suggestions:
        lines.extend(["## 调整意见", ""])
        lines.extend(f"- {str(item).strip()}" for item in suggestions if str(item).strip())
        lines.append("")

    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def _report_local_markdown(payload: dict[str, object], report: dict[str, object], generated_at: str) -> str:
    lines: list[str] = [
        f"## 执行记录（{generated_at}）",
        "",
        *_report_run_metadata_lines(payload, report, generated_at),
    ]
    lines.extend(
        _section_lines(
            "执行摘要",
            _batch_narrative_block(report),
        )
    )
    overview_rows = [
        ["剪辑成功数", report.get("剪辑成功数") or 0],
        ["发布提交数", report.get("发布提交数") or 0],
        ["发布成功数", report.get("发布成功数") or 0],
        ["发布处理中数", report.get("发布处理中数") or 0],
        ["失败数", len(report.get("发布失败任务") or [])],
    ]
    lines.extend(_section_lines("总体概览", _markdown_table(["指标", "数值"], overview_rows)))
    lines.extend(
        _section_lines(
            "任务明细",
            _markdown_table(
                ["序号", "账号", "平台", "剪辑手法", "去重手法", "视频时长", "发布情况", "失败原因"],
                [
                    [
                        item.get("序号"),
                        item.get("账号"),
                        item.get("平台"),
                        item.get("剪辑手法"),
                        item.get("去重手法"),
                        item.get("视频时长"),
                        item.get("发布情况"),
                        item.get("失败原因") or item.get("错误") or "",
                    ]
                    for item in (report.get("任务明细") if isinstance(report.get("任务明细"), list) else [])
                ],
            ),
        )
    )
    suggestions = _failed_publish_suggestions_zh(report)
    if suggestions:
        lines.extend(_section_lines("后续建议", suggestions))
    return "\n".join(lines).rstrip() + "\n"


def _report_generic_markdown(payload: dict[str, object], report: dict[str, object], generated_at: str) -> str:
    lines: list[str] = [
        f"## 执行记录（{generated_at}）",
        "",
        *_report_run_metadata_lines(payload, report, generated_at),
    ]
    lines.extend(
        _section_lines(
            "执行摘要",
            _batch_narrative_block(report),
        )
    )
    summary = str(payload.get("user_summary_zh") or "").strip()
    if summary:
        lines.extend(_section_lines("执行总结", summary.splitlines()))
    if report and str(os.getenv("BARRY_VIDEO_REPORT_DEBUG_JSON") or "").strip():
        lines.extend(
            _section_lines(
                "结构化结果",
                [
                    "```json",
                    json.dumps(report, ensure_ascii=False, indent=2),
                    "```",
                ],
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _report_markdown(payload: dict[str, object]) -> str:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    mode = str(payload.get("mode") or "").strip()
    if mode == "batch_drama":
        return _report_batch_markdown(payload, report, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    elif mode == "publish_analysis_daily":
        return _report_publish_analysis_markdown(payload, report, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    elif mode == "local_video":
        return _report_local_markdown(payload, report, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return _report_generic_markdown(payload, report, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def _report_has_meaningful_content(payload: dict[str, object]) -> bool:
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    mode = str(payload.get("mode") or "").strip()
    if mode == "publish_analysis_daily":
        return bool(report)
    if mode in {"batch_drama", "local_video", "retry_failed_publish"}:
        detail_lists = [
            report.get("任务明细"),
            report.get("发布成功视频"),
            report.get("发布失败任务"),
            report.get("账号发布结果"),
        ]
        return any(isinstance(value, list) and value for value in detail_lists)
    if mode == "run_round":
        stages = payload.get("stages")
        return bool(stages)
    return bool(report) or bool(str(payload.get("user_summary_zh") or "").strip())


def _maybe_write_test_summary(payload: dict[str, object]) -> dict[str, str] | dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    if str(payload.get("mode") or "").strip() == "cleanup_daily_artifacts":
        return {}
    if not _report_has_meaningful_content(payload):
        return {}
    mode = str(payload.get("mode") or "").strip()
    report_dir = _analysis_summary_dir() if mode == "publish_analysis_daily" else _test_summary_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    date_key = datetime.now().strftime("%Y%m%d")
    prefix = _report_filename_prefix_zh(payload)
    base_name = f"{prefix}_{date_key}"
    markdown_path = report_dir / f"{base_name}.md"
    markdown_path.write_text(_report_markdown(payload), encoding="utf-8")
    files = {
        "directory": str(report_dir),
        "markdown": str(markdown_path),
    }
    if mode == "publish_analysis_daily":
        return {"analysis_report_files": files}
    return {"test_report_files": files}


def _finalize_payload(payload: dict[str, object]) -> dict[str, object]:
    try:
        files = _maybe_write_test_summary(payload)
        if files:
            payload.update(files)
    except Exception as exc:
        key = "analysis_report_files" if str(payload.get("mode") or "").strip() == "publish_analysis_daily" else "test_report_files"
        payload[key] = {"error": str(exc)}
    if str(payload.get("mode") or "").strip() != "publish_analysis_daily":
        try:
            payload.update(_maybe_push_feishu_test_report(payload))
        except Exception as exc:
            payload["test_feishu_push"] = {"enabled": True, "error": str(exc)}
    return payload


def _failure_mode_from_command(command: str) -> str:
    mapping = {
        "run-batch-drama": "batch_drama",
        "run-local": "local_video",
        "publish-analysis-daily": "publish_analysis_daily",
        "retry-failed-publish": "retry_failed_publish",
        "discard-failed-publish-output": "discard_failed_publish_output",
        "show-failed-publish-paths": "show_failed_publish_paths",
        "show-round": "show_round",
    }
    return mapping.get(str(command or "").strip(), str(command or "run"))


def _build_failure_report_payload(args: argparse.Namespace, reason: str, *, status: str) -> dict[str, object] | None:
    command = str(getattr(args, "command", "") or "").strip()
    mode = _failure_mode_from_command(command)
    if mode not in {
        "run_round",
        "batch_drama",
        "local_video",
        "publish_analysis_daily",
        "retry_failed_publish",
        "discard_failed_publish_output",
        "show_failed_publish_paths",
        "show_round",
    }:
        return None

    report_zh: dict[str, object] = {
        "执行模式": _report_title_zh({"mode": mode}),
        "最终状态": "失败" if status != "interrupted" else "已中断",
        "失败原因": reason,
    }
    if getattr(args, "publish_platform", None):
        report_zh["目标平台"] = _platform_label(str(getattr(args, "publish_platform", "") or ""))
    if getattr(args, "count", None) is not None:
        report_zh["请求数量"] = int(getattr(args, "count", 0) or 0)
    if getattr(args, "round_id", None) is not None:
        report_zh["Round ID"] = int(getattr(args, "round_id", 0) or 0)

    user_summary = (
        f"{_report_title_zh({'mode': mode})}已被手动中断。原因：{reason}"
        if status == "interrupted"
        else f"{_report_title_zh({'mode': mode})}执行失败。原因：{reason}"
    )
    return {
        "status": status,
        "mode": mode,
        "report_zh": report_zh,
        "user_summary_zh": user_summary,
    }


def _resolve_local_publish_target(args: argparse.Namespace, db: FlywheelSQLite) -> dict[str, list[str] | str]:
    account_ids = [str(item).strip() for item in (args.account_id or []) if str(item).strip()]
    team_ids = [str(item).strip() for item in (args.team_id or []) if str(item).strip()]
    platform = normalize_publish_platform(args.publish_platform) if args.publish_platform else ""

    if not platform or (not account_ids and not team_ids):
        active_accounts = [
            {
                "id": str(account.get("publish_account_id") or account.get("id") or ""),
                "team_id": str(account.get("team_id") or ""),
                "platform": str(account.get("platform") or ""),
                "name": str(account.get("social_name") or "").strip() or f"{account.get('platform') or ''} 账号",
                "agent_id": str(account.get("agent_id") or ""),
                "status": str(account.get("status") or "active"),
            }
            for account in (dict(row) for row in db.list_accounts())
            if str(account.get("status") or "active") == "active"
        ]
        choices_zh = [
            {
                "序号": index + 1,
                "平台": str(account.get("platform") or ""),
                "账号": str(account.get("name") or ""),
            }
            for index, account in enumerate(active_accounts)
        ]
        raise SystemExit(
            json.dumps(
                {
                    "status": "needs_publish_choice",
                    "message": "真实发布前必须由用户明确选择发布平台和账号。请向用户展示 choices_zh，让用户选择平台和账号；accounts 仅供内部执行使用。",
                    "required": ["--publish-platform", "--account-id 或 --team-id"],
                    "choices_zh": choices_zh,
                    "accounts": active_accounts,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    resolved = resolve_publish_targets(
        SimpleNamespace(account_id=account_ids, team_id=team_ids, platform=platform)
    )
    resolved_platform = str(resolved.get("social_type") or platform or "")
    resolved_team_ids = [str(item).strip() for item in (resolved.get("team_ids") or []) if str(item).strip()]
    resolved_accounts = [
        {
            "team_id": str(account.get("team_id") or "").strip(),
            "platform": resolved_platform,
            "name": str(account.get("social_name") or "").strip() or f"{resolved_platform} 账号",
            "social_name": str(account.get("social_name") or "").strip(),
        }
        for account in (resolved.get("accounts") or [])
        if str(account.get("team_id") or "").strip()
    ]
    if not resolved_accounts:
        resolved_accounts = [
            {
                "team_id": team_id,
                "platform": resolved_platform,
                "name": f"{_platform_label(resolved_platform)} 账号",
                "social_name": "",
            }
            for team_id in resolved_team_ids
        ]

    return {
        "account_ids": account_ids,
        "team_ids": resolved_team_ids,
        "platform": resolved_platform,
        "accounts": resolved_accounts,
    }


def _resolve_local_caption(args: argparse.Namespace, default_text: str) -> str:
    if str(args.text or "").strip():
        return str(args.text or "").strip()
    if args.text_file:
        path = Path(args.text_file).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"文案文件不存在: {path}")
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return str(default_text or "").strip()


def _find_publish_record(*, platform: str, team_id: str, task_id: str) -> dict:
    if not platform or not team_id or not task_id:
        return {}
    for page in range(1, 4):
        body = require_success(
            get_publish_records(page=page, page_size=100, social_type=platform),
            f"获取 {platform} 发布记录",
        )
        items = body.get("items") if isinstance(body.get("items"), list) else []
        if not items:
            return {}
        for item in items:
            if str(item.get("team_id") or "") == team_id and str(item.get("task_id") or "") == task_id:
                return dict(item)
    return {}


def _poll_local_publish_records(*, platform: str, tasks: list[dict], wait_seconds: int, poll_interval: int) -> list[dict]:
    deadline = time.time() + max(0, wait_seconds)
    records: list[dict] = []
    last_error = ""
    while True:
        try:
            records = [
                _find_publish_record(
                    platform=platform,
                    team_id=str(task.get("team_id") or ""),
                    task_id=str(task.get("task_id") or ""),
                )
                for task in tasks
            ]
        except Exception as exc:
            last_error = str(exc).strip()
            _emit_stderr_line(
                f"[publish-record-poll] {platform} 发布记录查询失败，继续重试：{last_error}"
            )
            if time.time() >= deadline:
                _emit_stderr_line(
                    f"[publish-record-poll] {platform} 发布记录查询超时收尾，保留空记录返回。"
                )
                return records
            time.sleep(max(1, poll_interval))
            continue
        statuses = [str(record.get("status") or task.get("status") or "") for record, task in zip(records, tasks)]
        if statuses and not any(status.upper() in RUNNING_PUBLISH_STATUSES for status in statuses):
            return records
        if time.time() >= deadline:
            if last_error:
                _emit_stderr_line(
                    f"[publish-record-poll] {platform} 发布记录查询截止，最近错误：{last_error}"
                )
            return records
        time.sleep(max(1, poll_interval))


def _cleanup_generated_files(paths: list[str]) -> dict[str, object]:
    deleted: list[str] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in paths:
        path = Path(str(item or "")).expanduser()
        if not str(path) or str(path) in seen or not path.exists():
            continue
        seen.add(str(path))
        allowed, reason = _validate_cleanup_target(path)
        if not allowed:
            errors.append({"path": str(path), "error": reason})
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            deleted.append(str(path))
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {"deleted_paths": deleted, "errors": errors}


def _set_failed_publish_state(payload: dict | None) -> None:
    save_state({FAILED_PUBLISH_STATE_KEY: payload or None})


def _get_failed_publish_state() -> dict:
    state = load_state()
    payload = state.get(FAILED_PUBLISH_STATE_KEY)
    return dict(payload) if isinstance(payload, dict) else {}


def _failed_publish_clip_paths(items: list[dict]) -> list[str]:
    paths: list[str] = []
    for item in items:
        clip = item.get("clip") or {}
        for value in (clip.get("downloaded_file"), clip.get("publish_ready_file")):
            path = str(value or "").strip()
            if path:
                paths.append(path)
    return paths


def _probe_video_safely(path: str) -> dict[str, object]:
    if not path:
        return {}
    try:
        return dict(probe_video(path))
    except Exception as exc:
        return {"error": str(exc)}


def _materialize_clip_artifacts(
    *,
    source_context: dict,
    clip_task: dict,
    merge_video: bool,
    submit_timeout: int,
    task_timeout: int,
    poll_interval: float,
    output_dir: Path,
    target_width: int,
    target_height: int,
) -> dict[str, object]:
    submit = submit_ws_tasks(
        window_id=source_context["window_id"],
        upload_ids=[source_context["upload_id"]],
        tasks=[clip_task],
        merge_video=merge_video,
        timeout=submit_timeout,
    )
    manus_id = submit.get("manus_id")
    if not manus_id:
        raise RuntimeError(f"剪辑任务未返回 manus_id: {json.dumps(submit, ensure_ascii=False)}")

    manus = wait_for_manus(manus_id, timeout=task_timeout, poll_interval=poll_interval)
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded_file = download_manus(manus_id, output_dir=str(output_dir))
    publish_ready_file = _ensure_vertical_publish_file(
        downloaded_file,
        target_width=target_width,
        target_height=target_height,
    )
    return {
        "task": clip_task,
        "submit": submit,
        "manus_id": str(manus_id),
        "manus_status": manus.get("status"),
        "downloaded_file": downloaded_file,
        "publish_ready_file": publish_ready_file,
        "downloaded_metadata": _probe_video_safely(downloaded_file),
        "publish_ready_metadata": _probe_video_safely(publish_ready_file),
    }


PUBLISH_TO_PROMOTION_PLATFORM = {
    "TIKTOK": 1,
    "FACEBOOK": 2,
    "INSTAGRAM": 3,
    "YOUTUBE": 4,
}


def _resolve_batch_publish_targets(args: argparse.Namespace) -> dict[str, object]:
    return _bound_batch_drama_cli()._resolve_batch_publish_targets(args)


def _select_batch_dramas(args: argparse.Namespace, config, *, target_count: int | None = None) -> list[dict]:
    return _bound_batch_drama_cli()._select_batch_dramas(args, config, target_count=target_count)


def _batch_episode_order(row: dict) -> int:
    return _bound_batch_drama_cli()._batch_episode_order(row)


def _has_playable_episode_asset(row: dict, info=None) -> bool:
    return _bound_batch_drama_cli()._has_playable_episode_asset(row, info)


def _select_or_validate_batch_episode(drama: dict, args: argparse.Namespace) -> dict:
    return _bound_batch_drama_cli()._select_or_validate_batch_episode(drama, args)


def _batch_episode_precheck_targets(dramas: list[dict], count: int, args: argparse.Namespace) -> list[dict]:
    return _bound_batch_drama_cli()._batch_episode_precheck_targets(dramas, count, args)


def _select_batch_playable_dramas(
    args: argparse.Namespace,
    config,
    *,
    target_count: int | None = None,
) -> tuple[list[dict], list[dict[str, str]]]:
    return _bound_batch_drama_cli()._select_batch_playable_dramas(args, config, target_count=target_count)


def _batch_safety_gate_item(item: dict, platform: str, *, prefetch_promotion: bool) -> dict:
    return _bound_batch_drama_cli()._batch_safety_gate_item(item, platform, prefetch_promotion=prefetch_promotion)


def _run_batch_safety_gate(items: list[dict], platform: str, *, prefetch_promotion: bool) -> tuple[list[dict], list[dict]]:
    return _bound_batch_drama_cli()._run_batch_safety_gate(items, platform, prefetch_promotion=prefetch_promotion)


def _format_batch_safety_reject(item: dict, *, replaced: bool | None = None) -> dict[str, object]:
    return _bound_batch_drama_cli()._format_batch_safety_reject(item, replaced=replaced)


def _backfill_batch_safety_gate(
    *,
    approved_items: list[dict],
    rejected_items: list[dict],
    reserve_sources: list[dict],
    args: argparse.Namespace,
    platform: str,
    prefetch_promotion: bool,
) -> tuple[list[dict], list[dict], dict[str, object]]:
    return _bound_batch_drama_cli()._backfill_batch_safety_gate(
        approved_items=approved_items,
        rejected_items=rejected_items,
        reserve_sources=reserve_sources,
        args=args,
        platform=platform,
        prefetch_promotion=prefetch_promotion,
    )


def _strategy_memory_meta(config) -> dict[str, object]:
    return _bound_batch_drama_cli()._strategy_memory_meta(config)


def _account_profile_lookup_keys(account: dict[str, object]) -> list[str]:
    return _bound_batch_drama_cli()._account_profile_lookup_keys(account)


def _lookup_account_assignment_profile(
    account: dict[str, object],
    profiles: dict[str, dict[str, object]],
) -> dict[str, object]:
    return _bound_batch_drama_cli()._lookup_account_assignment_profile(account, profiles)


def _candidate_language_matches_profile(candidate: dict[str, object], profile: dict[str, object]) -> bool:
    return _bound_batch_drama_cli()._candidate_language_matches_profile(candidate, profile)


def _candidate_blocked_by_profile(candidate: dict[str, object], profile: dict[str, object]) -> bool:
    return _bound_batch_drama_cli()._candidate_blocked_by_profile(candidate, profile)


def _candidate_hits_account_cooldown(candidate: dict[str, object], profile: dict[str, object]) -> bool:
    return _bound_batch_drama_cli()._candidate_hits_account_cooldown(candidate, profile)


def _candidate_assignment_sort_key(
    candidate: dict[str, object],
    profile: dict[str, object],
) -> tuple[int, int, float, str]:
    return _bound_batch_drama_cli()._candidate_assignment_sort_key(candidate, profile)


def _assign_candidates_to_accounts(
    selected_sources: list[dict],
    accounts: list[dict],
    *,
    recent_days: int = 14,
) -> list[tuple[dict, dict]]:
    return _bound_batch_drama_cli()._assign_candidates_to_accounts(
        selected_sources,
        accounts,
        recent_days=recent_days,
    )


def _clone_reused_batch_source(source: dict, *, reuse_index: int) -> dict[str, object]:
    return _bound_batch_drama_cli()._clone_reused_batch_source(source, reuse_index=reuse_index)


def _source_identity(source: dict) -> tuple[str, str, str]:
    return _bound_batch_drama_cli()._source_identity(source)


def _source_is_external_video(source: dict) -> bool:
    return _bound_batch_drama_cli()._source_is_external_video(source)


def _source_external_output_capacity(source: dict) -> int:
    return _bound_batch_drama_cli()._source_external_output_capacity(source)


def _prioritize_batch_sources(
    sources: list[dict],
    *,
    requested_count: int,
) -> tuple[list[dict], list[dict], dict[str, int]]:
    return _bound_batch_drama_cli()._prioritize_batch_sources(sources, requested_count=requested_count)


def _expand_batch_sources_with_reuse(
    sources: list[dict],
    *,
    requested_count: int,
) -> tuple[list[dict], int]:
    return _bound_batch_drama_cli()._expand_batch_sources_with_reuse(sources, requested_count=requested_count)


def _build_batch_plan_item(
    *,
    slot_index: int,
    account: dict,
    source: dict,
    cut_type_pool: list[str],
    dedup_pool: list[str],
    duration: int,
    watermark: bool,
) -> dict[str, object]:
    return _bound_batch_drama_cli()._build_batch_plan_item(
        slot_index=slot_index,
        account=account,
        source=source,
        cut_type_pool=cut_type_pool,
        dedup_pool=dedup_pool,
        duration=duration,
        watermark=watermark,
    )


def _build_batch_replacement_item(slot_item: dict, source: dict, *, attempt_no: int) -> dict[str, object]:
    return _bound_batch_drama_cli()._build_batch_replacement_item(slot_item, source, attempt_no=attempt_no)


def _build_batch_plan(args: argparse.Namespace, config) -> dict[str, object]:
    return _bound_batch_drama_cli()._build_batch_plan(args, config)


def _record_batch_learning_logs(*, round_id: int, items: list[dict], safety_rejected: list[dict], report_zh: dict, config) -> None:
    return _bound_batch_drama_cli()._record_batch_learning_logs(
        round_id=round_id,
        items=items,
        safety_rejected=safety_rejected,
        report_zh=report_zh,
        config=config,
    )


def _clip_batch_item(item: dict, args: argparse.Namespace, config) -> dict:
    return _bound_batch_drama_cli()._clip_batch_item(item, args, config)


def _promotion_caption(item: dict, platform: str) -> dict[str, str]:
    return _bound_batch_drama_cli()._promotion_caption(item, platform)


def _publish_batch_item(item: dict, args: argparse.Namespace, platform: str, attempt: int) -> dict:
    return _bound_batch_drama_cli()._publish_batch_item(item, args, platform, attempt)


def _merge_publish_attempt_result(state_by_index: dict[int, dict], item: dict) -> None:
    state_by_index[int(item.get("index") or 0)] = item


def _is_non_retryable_publish_error(message: str) -> bool:
    normalized = str(message or "").strip().lower()
    return bool(normalized) and any(pattern.lower() in normalized for pattern in NON_RETRYABLE_PUBLISH_ERROR_PATTERNS)


def _item_non_retryable_publish_reason(item: dict, records_by_key: dict[tuple[str, str], dict]) -> str:
    if _is_non_retryable_publish_error(str(item.get("error") or "")):
        return str(item.get("error") or "")
    attempts = item.get("publish_attempts") if isinstance(item.get("publish_attempts"), list) else []
    for attempt in reversed(attempts):
        message = str((attempt or {}).get("error") or "").strip()
        if _is_non_retryable_publish_error(message):
            return message
    for record in _item_publish_records(item, records_by_key):
        message = str(record.get("error_msg") or record.get("message") or "").strip()
        if _is_non_retryable_publish_error(message):
            return message
    return ""


def _item_should_retry_publish(item: dict, records_by_key: dict[tuple[str, str], dict]) -> bool:
    if _item_non_retryable_publish_reason(item, records_by_key):
        return False
    if item.get("status") == "failed":
        return True
    publish = item.get("publish") or {}
    tasks = publish.get("tasks") or []
    if not tasks:
        return True
    records = _item_publish_records(item, records_by_key)
    if any(str(record.get("status") or "").upper() in SUCCESSFUL_PUBLISH_STATUSES for record in records):
        return False
    statuses = [str(record.get("status") or "").upper() for record in records if str(record.get("status") or "")] or [
        str(task.get("status") or "").upper() for task in tasks if str(task.get("status") or "")
    ]
    if any(status in RUNNING_PUBLISH_STATUSES for status in statuses):
        return False
    if not statuses:
        return True
    return all(status in FINAL_FAILURE_PUBLISH_STATUSES for status in statuses)


def _publish_batch_with_retries(
    items: list[dict],
    args: argparse.Namespace,
    platform: str,
    *,
    max_attempts: int | None = None,
) -> tuple[list[dict], list[dict]]:
    return _bound_batch_drama_cli()._publish_batch_with_retries(
        items,
        args,
        platform,
        max_attempts=max_attempts,
    )


def _run_parallel(items: list[dict], max_workers: int, worker):
    results: list[dict] = []
    if max_workers <= 1:
        for item in items:
            try:
                results.append(worker(item))
            except Exception as exc:
                results.append({**item, "status": "failed", "error": str(exc)})
        return results

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(worker, item): item for item in items}
        for future in as_completed(future_map):
            original = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:  # keep batch-level visibility instead of losing the failed item
                results.append({**original, "status": "failed", "error": str(exc)})
    results.sort(key=lambda item: int(item.get("index") or 0))
    return results


def _cut_type_zh(value: str) -> str:
    return _bound_publish_reporting()._cut_type_zh(value)


def _dedup_list_zh(values) -> str:
    return _bound_publish_reporting()._dedup_list_zh(values)


def _task_keys(tasks: list[dict]) -> set[tuple[str, str]]:
    return _bound_publish_reporting()._task_keys(tasks)


def _record_by_task_key(records: list[dict]) -> dict[tuple[str, str], dict]:
    return _bound_publish_reporting()._record_by_task_key(records)


def _item_publish_records(item: dict, records_by_key: dict[tuple[str, str], dict]) -> list[dict]:
    return _bound_publish_reporting()._item_publish_records(item, records_by_key)


def _clip_video_info(item: dict) -> dict[str, object]:
    return _bound_publish_reporting()._clip_video_info(item)


def _batch_item_publish_outcome(item: dict, records: list[dict], tasks: list[dict]) -> str:
    return _bound_publish_reporting()._batch_item_publish_outcome(item, records, tasks)


def _batch_item_failure_reason(item: dict, records: list[dict]) -> str:
    return _bound_publish_reporting()._batch_item_failure_reason(item, records)


def _is_processing_publish_outcome(report: dict) -> bool:
    return _bound_publish_reporting()._is_processing_publish_outcome(report)


def _is_success_publish_outcome(report: dict) -> bool:
    return _bound_publish_reporting()._is_success_publish_outcome(report)


def _is_failed_publish_outcome(report: dict) -> bool:
    return _bound_publish_reporting()._is_failed_publish_outcome(report)


def _publish_account_names(records: list[dict], target: dict, fallback_platform: str) -> list[str]:
    return _bound_publish_reporting()._publish_account_names(records, target, fallback_platform)


def _publish_item_report(item: dict, records_by_key: dict[tuple[str, str], dict], cleanup_deleted: set[str]) -> dict:
    return _bound_publish_reporting()._publish_item_report(item, records_by_key, cleanup_deleted)


def _mark_processing_items_as_failed(
    *,
    items: list[dict],
    records: list[dict],
    cleanup_deleted: set[str],
    reason: str,
) -> None:
    return _bound_publish_reporting()._mark_processing_items_as_failed(
        items=items,
        records=records,
        cleanup_deleted=cleanup_deleted,
        reason=reason,
    )


def _settle_publish_report_payload(
    payload: dict,
    *,
    platform: str,
    wait_seconds: int,
    poll_interval: int,
    settle_timeout_seconds: int,
    report_builder,
) -> dict:
    return _bound_publish_reporting()._settle_publish_report_payload(
        payload,
        platform=platform,
        wait_seconds=wait_seconds,
        poll_interval=poll_interval,
        settle_timeout_seconds=settle_timeout_seconds,
        report_builder=report_builder,
    )


def _bound_batch_drama_cli():
    return batch_drama_cli_module.bind(sys.modules[__name__])


def _bound_publish_reporting():
    return publish_reporting_module.bind(sys.modules[__name__])


def _batch_report_zh(payload: dict) -> dict:
    return _bound_batch_drama_cli()._batch_report_zh(payload)


def _local_report_zh(payload: dict) -> dict:
    return _bound_publish_reporting()._local_report_zh(payload)


def _retryable_batch_items(items: list[dict], records: list[dict]) -> list[dict]:
    return _bound_publish_reporting()._retryable_batch_items(items, records)


def _failed_publish_state_payload(*, mode: str, platform: str, items: list[dict], records: list[dict]) -> dict | None:
    return _bound_publish_reporting()._failed_publish_state_payload(
        mode=mode,
        platform=platform,
        items=items,
        records=records,
    )


def _failed_publish_prompt_zh(report: dict) -> str:
    return _bound_publish_reporting()._failed_publish_prompt_zh(report)


def _failed_publish_suggestions_zh(report: dict) -> list[str]:
    return _bound_publish_reporting()._failed_publish_suggestions_zh(report)


def _failed_publish_paths_payload(state: dict) -> dict:
    return _bound_publish_reporting()._failed_publish_paths_payload(state)


def _join_non_empty(values: list[str], sep: str = "，") -> str:
    return sep.join(value for value in values if str(value or "").strip())


def _format_elapsed_zh(seconds: float | int | None) -> str:
    total = int(round(float(seconds or 0)))
    if total <= 0:
        return ""
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分")
    if secs or not parts:
        parts.append(f"{secs}秒")
    return "".join(parts)


def _format_timing_zh(timings: dict) -> dict[str, str]:
    formatted: dict[str, str] = {}
    for key, value in timings.items():
        label = _format_elapsed_zh(value)
        if label:
            formatted[str(key)] = label
    return formatted


def _batch_detail_block_zh(item: dict) -> str:
    return _bound_batch_drama_cli()._batch_detail_block_zh(item)


def _batch_user_summary_zh(report: dict) -> str:
    return _bound_batch_drama_cli()._batch_user_summary_zh(report)


def _local_user_summary_zh(report: dict) -> str:
    return _bound_publish_reporting()._local_user_summary_zh(report)


def cmd_run_batch_drama(args: argparse.Namespace) -> None:
    return _bound_batch_drama_cli().cmd_run_batch_drama(args)


def cmd_run_local(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    ensure_runtime_dirs(config)
    if args.publish_concurrency is None:
        args.publish_concurrency = config.publish_execute_concurrency
    db = FlywheelSQLite(Path(config.database_path))
    db.init_schema(schema_path())

    source_path = Path(args.file).expanduser().resolve()
    if not source_path.exists():
        raise SystemExit(f"本地视频不存在: {source_path}")

    target = _resolve_local_publish_target(args, db)
    upload_context = upload_video(
        str(source_path),
        timeout=args.upload_timeout,
        poll_interval=args.poll_interval,
    )
    clip_task = {"key": HIGH_CUT_TASK_KEY, "params": build_high_cut_params(args)}
    output_dir = Path(args.download_dir).expanduser().resolve() if args.download_dir else Path(config.clipped_dir) / "local"
    try:
        clip_result = _materialize_clip_artifacts(
            source_context=upload_context,
            clip_task=clip_task,
            merge_video=args.merge_video,
            submit_timeout=args.submit_timeout,
            task_timeout=args.timeout,
            poll_interval=args.poll_interval,
            output_dir=output_dir,
            target_width=config.clip_target_width,
            target_height=config.clip_target_height,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    manus_id = str(clip_result.get("manus_id") or "")
    downloaded_file = str(clip_result.get("downloaded_file") or "")
    publish_ready_file = str(clip_result.get("publish_ready_file") or "")
    downloaded_metadata = dict(clip_result.get("downloaded_metadata") or {})
    publish_ready_metadata = dict(clip_result.get("publish_ready_metadata") or {})
    clip_options = {
        "cut_type": args.cut_type,
        "duration": args.duration,
        "output_count": 1,
        "script_count": 1,
        "deduplication": args.deduplication or DEFAULT_DEDUPLICATION,
        "watermark": args.watermark,
        "target_aspect_ratio": "9:16",
    }
    caption = _resolve_local_caption(args, source_path.stem)
    title = str(getattr(args, "title", "") or "").strip() or source_path.stem
    account_items = list(target.get("accounts") or [])
    publish_items = [
        {
            "index": index + 1,
            "source_path": str(source_path),
            "account": dict(account),
            "title": title,
            "caption": caption,
            "promotion": {
                "title": title,
                "caption": caption,
                "promotion_link": "",
                "promotion_code": "",
            },
            "clip_options": dict(clip_options),
            "clip": dict(clip_result),
        }
        for index, account in enumerate(account_items)
    ]
    publish_items, records = _publish_batch_with_retries(
        publish_items,
        args,
        str(target.get("platform") or ""),
    )
    tasks = [
        task
        for item in publish_items
        for task in (((item.get("publish") or {}).get("tasks")) or [])
    ]
    publish_target = {
        "social_type": str(target.get("platform") or ""),
        "accounts": account_items,
        "team_ids": [str(account.get("team_id") or "") for account in account_items if str(account.get("team_id") or "")],
    }
    statuses = [str(record.get("status") or "") for record in records if str(record.get("status") or "")] or [
        str(task.get("status") or "") for task in tasks if str(task.get("status") or "")
    ]
    should_cleanup = (
        not args.keep_output
        and statuses
        and all(status.upper() in SUCCESSFUL_PUBLISH_STATUSES for status in statuses)
    )
    cleanup = (
        _cleanup_generated_files([downloaded_file, publish_ready_file])
        if should_cleanup
        else {"deleted_paths": [], "errors": []}
    )
    local_payload = {
        "platform": str(target.get("platform") or ""),
        "items": publish_items,
        "publish_records": records,
        "cleanup": {
            "enabled": not args.keep_output,
            "executed": should_cleanup,
            **cleanup,
        },
    }
    local_payload = _settle_publish_report_payload(
        local_payload,
        platform=str(target.get("platform") or ""),
        wait_seconds=int(args.collect_wait_seconds),
        poll_interval=int(args.collect_poll_interval),
        settle_timeout_seconds=int(config.collect_settle_timeout_seconds),
        report_builder=_local_report_zh,
    )
    report_zh = dict(local_payload.get("report_zh") or {})
    user_summary_zh = _local_user_summary_zh(report_zh)
    failed_state = _failed_publish_state_payload(
        mode="local_video",
        platform=str(target.get("platform") or ""),
        items=publish_items,
        records=local_payload.get("publish_records") if isinstance(local_payload.get("publish_records"), list) else records,
    )
    _set_failed_publish_state(failed_state)

    payload = {
        "status": "done",
        "mode": "local_video",
        "source_file": str(source_path),
        "upload": upload_context,
        "clip": {
            **clip_result,
            "options": clip_options,
        },
        "publish": {
            "platform": publish_target.get("social_type") or target.get("platform"),
            "target": publish_target,
            "items": publish_items,
            "tasks": tasks,
            "records": records,
            "statuses": statuses,
        },
        "cleanup": {
            "enabled": not args.keep_output,
            "executed": should_cleanup,
            **cleanup,
        },
        "report_zh": report_zh,
        "user_summary_zh": user_summary_zh,
        "retry_prompt_zh": _failed_publish_prompt_zh(report_zh),
    }
    payload = _finalize_payload(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _safe_int(value: object) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: object) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fetch_all_publish_analysis(
    *,
    platform: str,
    social_id: str,
    start_date: str,
    end_date: str,
    page_size: int,
    max_pages: int,
) -> dict[str, object]:
    items: list[dict[str, object]] = []
    summary_view = 0
    summary_interaction = 0
    summary_revenue = 0.0
    total_count = 0
    for page in range(1, max_pages + 1):
        body = require_success(
            get_publish_analysis(
                page=page,
                page_size=page_size,
                social_type=platform,
                social_id=social_id,
                start_date=start_date,
                end_date=end_date,
            ),
            "获取发布数据分析",
        )
        page_items = body.get("items") if isinstance(body.get("items"), list) else []
        if page == 1:
            total_count = _safe_int((body.get("page") or {}).get("total_count"))
            summary_view = _safe_int(body.get("view"))
            summary_interaction = _safe_int(body.get("interaction"))
            summary_revenue = _safe_float(body.get("order_amount"))
        if not page_items:
            break
        items.extend(dict(item) for item in page_items if isinstance(item, dict))
        if total_count and len(items) >= total_count:
            break
    return {
        "items": items,
        "view": summary_view,
        "interaction": summary_interaction,
        "order_amount": round(summary_revenue, 2),
        "total_count": total_count or len(items),
    }


def _fetch_publish_record_summary(
    *,
    platform: str,
    social_id: str,
    start_date: str,
    end_date: str,
    page_size: int,
    max_pages: int,
) -> dict[str, int]:
    total_records = 0
    success_records = 0
    processing_records = 0
    failed_records = 0
    seen_keys: set[str] = set()

    for page in range(1, max(1, max_pages) + 1):
        body = require_success(
            get_publish_records(
                page=page,
                page_size=max(1, page_size),
                post_status=0,
                social_type=platform,
                social_id=social_id,
                start_date=start_date,
                end_date=end_date,
            ),
            "获取发布记录",
        )
        page_items = body.get("items") if isinstance(body.get("items"), list) else []
        if page == 1:
            total_records = _safe_int(body.get("total_count"))
        if not page_items:
            break
        for index, item in enumerate(page_items):
            key = str(item.get("id") or item.get("post_id") or item.get("task_id") or f"{page}:{index}").strip()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            status = str(item.get("status") or "").strip().upper()
            if status in SUCCESSFUL_PUBLISH_STATUSES:
                success_records += 1
            elif status in RUNNING_PUBLISH_STATUSES:
                processing_records += 1
            elif status:
                failed_records += 1
        if len(page_items) < max(1, page_size):
            break
        if total_records and len(seen_keys) >= total_records:
            break

    if total_records <= 0:
        total_records = len(seen_keys)

    return {
        "当日发布视频总数": total_records,
        "当日发布成功数": success_records,
        "发布处理中数量": processing_records,
        "发布失败数量": failed_records,
    }


def _fetch_income_daily_summary(
    *,
    platform: str,
    start_date: str,
    end_date: str,
) -> dict[str, float | int]:
    platform_key = _platform_numeric_key(platform)
    base_params = {
        "start_time": start_date[:10],
        "end_time": end_date[:10],
        "task_type": 0,
        "app_id": "",
        "share_type": 0,
        "language": 0,
        "serial_name": "",
        "order_type": 0,
        "platform": platform_key,
    }
    income_body = require_success(
        get_income_aggregation(**base_params),
        "获取收益聚合",
    )
    click_body = require_success(
        get_income_click_aggregation(**base_params, need_group=1),
        "获取点击聚合",
    )
    income_total = income_body.get("total") if isinstance(income_body.get("total"), dict) else income_body
    click_total = click_body.get("total") if isinstance(click_body.get("total"), dict) else click_body
    if not isinstance(income_total, dict):
        income_total = {}
    if not isinstance(click_total, dict):
        click_total = {}
    total_income = round(
        _safe_float(income_total.get("total_income") or income_total.get("share_amount")),
        2,
    )
    total_order_count = _safe_int(
        income_total.get("total_recharge_count")
        or income_total.get("order_count")
    )
    total_order_amount = round(
        _safe_float(income_total.get("total_recharge_order_amount") or income_total.get("order_amount")),
        2,
    )
    total_ad_amount = round(
        _safe_float(income_total.get("total_ad_order_amount") or income_total.get("ad_amount")),
        2,
    )
    total_click_count = _safe_int(
        click_total.get("total_click_count")
        or click_total.get("total_clicks")
        or income_total.get("total_click_count")
        or income_total.get("click_count")
    )
    return {
        "推广链接点击次数": total_click_count,
        "订单数": total_order_count,
        "订单金额": total_order_amount,
        "广告金额": total_ad_amount,
        "分佣金额": total_income,
        "总收益": total_income,
    }


def _platform_numeric_key(platform: str) -> int:
    normalized = str(platform or "").strip().upper()
    for platform_id, platform_name in PROMOTION_PLATFORMS.items():
        if str(platform_name or "").strip().upper() == normalized:
            return int(platform_id)
    return 0


def _load_creator_enum_maps(task_type: str = "1") -> tuple[dict[str, str], dict[str, str]]:
    try:
        body = require_success(get_creator_enum(task_type=task_type), "获取任务枚举")
    except Exception:
        return {}, {}
    language_rows = body.get("language") if isinstance(body.get("language"), list) else []
    app_rows = body.get("app") if isinstance(body.get("app"), dict) else {}
    language_map = {
        str(item.get("id") or "").strip(): str(item.get("name") or "").strip()
        for item in language_rows
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    app_map: dict[str, str] = {}
    for key, value in app_rows.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(value, dict):
            app_map[normalized_key] = str(value.get("app_name") or value.get("name") or "").strip()
        else:
            app_map[normalized_key] = str(value or "").strip()
    return language_map, app_map


def _fetch_all_my_task_rows(
    *,
    task_type: str,
    page_size: int,
    max_pages: int,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    total_count = 0
    for page in range(1, max_pages + 1):
        body = require_success(
            get_my_task_list(page=page, page_size=page_size, task_type=task_type),
            "获取我的任务列表",
        )
        page_rows = body.get("data") if isinstance(body.get("data"), list) else []
        rows.extend(dict(item) for item in page_rows if isinstance(item, dict))
        total_count = _safe_int((body.get("page") or {}).get("total_count"))
        if not page_rows:
            break
        if total_count and len(rows) >= total_count:
            break
    return {
        "items": rows,
        "total_count": total_count or len(rows),
    }


def _creator_task_platform_metrics(task: dict[str, object], platform_key: int) -> dict[str, object]:
    rows = task.get("platform_list") if isinstance(task.get("platform_list"), list) else []
    if platform_key <= 0:
        return {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _safe_int(row.get("platform")) == int(platform_key):
            return row
    return {}


def _build_my_task_dimension(
    *,
    task_rows: list[dict[str, object]],
    normalized_platform: str,
    language_map: dict[str, str],
    app_map: dict[str, str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    platform_key = _platform_numeric_key(normalized_platform)
    dimension_rows: list[dict[str, object]] = []
    total_clicks = 0
    total_orders = 0
    total_order_amount = 0.0
    total_ad_amount = 0.0
    total_share_amount = 0.0
    platform_task_count = 0
    active_tasks = 0
    ordered_tasks = 0

    for task in task_rows:
        task_platform = _creator_task_platform_metrics(task, platform_key)
        platform_clicks = _safe_int(task_platform.get("click_count"))
        platform_orders = _safe_int(task_platform.get("order_count"))
        platform_order_amount = round(_safe_float(task_platform.get("order_amount")), 2)
        platform_ad_amount = round(_safe_float(task_platform.get("ad_amount")), 2)
        platform_share_amount = round(_safe_float(task_platform.get("share_amount")), 2)
        total_clicks += platform_clicks
        total_orders += platform_orders
        total_order_amount += platform_order_amount
        total_ad_amount += platform_ad_amount
        total_share_amount += platform_share_amount
        if platform_clicks > 0 or platform_orders > 0 or platform_share_amount > 0 or platform_order_amount > 0:
            platform_task_count += 1
        if _safe_int(task.get("click_count")) > 0:
            active_tasks += 1
        if _safe_int(task.get("order_count")) > 0:
            ordered_tasks += 1

        app_id = str(task.get("app_id") or "").strip()
        language_key = str(task.get("language") or "").strip()
        dimension_rows.append(
            {
                "短剧": str(task.get("title") or task.get("serial_name") or "").strip() or "未命名短剧",
                "短剧ID": str(task.get("serial_id") or "").strip(),
                "剧场": str(task.get("app_name") or app_map.get(app_id) or _app_label(app_id) or "").strip(),
                "语言": str(language_map.get(language_key) or _language_zh(language_key) or language_key or "-").strip() or "-",
                "推广时间": str(task.get("actived_at") or "-").strip() or "-",
                "本平台点击": platform_clicks,
                "本平台订单": platform_orders,
                "本平台充值金额": platform_order_amount,
                "本平台广告金额": platform_ad_amount,
                "本平台分佣": platform_share_amount,
                "总点击": _safe_int(task.get("click_count")),
                "总订单": _safe_int(task.get("order_count")),
                "总分佣": round(_safe_float(task.get("share_amount")), 2),
            }
        )

    dimension_rows.sort(
        key=lambda item: (
            -_safe_float(item.get("本平台分佣")),
            -_safe_int(item.get("本平台点击")),
            -_safe_int(item.get("总点击")),
            str(item.get("短剧") or ""),
        )
    )

    overview = {
        "任务总数": len(task_rows),
        "当前平台有数据任务数": platform_task_count,
        "有点击任务数": active_tasks,
        "有订单任务数": ordered_tasks,
        "当前平台累计点击": total_clicks,
        "当前平台累计订单": total_orders,
        "当前平台累计充值金额": round(total_order_amount, 2),
        "当前平台累计广告金额": round(total_ad_amount, 2),
        "当前平台累计分佣": round(total_share_amount, 2),
    }
    return overview, dimension_rows


def _build_my_novel_task_dimension(
    *,
    task_rows: list[dict[str, object]],
    normalized_platform: str,
    language_map: dict[str, str],
    app_map: dict[str, str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    overview, base_rows = _build_my_task_dimension(
        task_rows=task_rows,
        normalized_platform=normalized_platform,
        language_map=language_map,
        app_map=app_map,
    )
    dimension_rows: list[dict[str, object]] = []
    for item in base_rows:
        row = dict(item)
        title = str(row.pop("短剧", "") or "").strip()
        row["小说"] = title or "未命名小说"
        row["平台应用"] = str(row.get("剧场") or "").strip()
        dimension_rows.append(row)
    return overview, dimension_rows


def _summarize_my_task_theaters(task_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    buckets: dict[str, dict[str, object]] = {}
    for item in task_rows:
        theater = str(item.get("剧场") or "").strip() or "未知剧场"
        bucket = buckets.setdefault(
            theater,
            {
                "剧场": theater,
                "任务数": 0,
                "点击": 0,
                "订单": 0,
                "分佣": 0.0,
            },
        )
        bucket["任务数"] = _safe_int(bucket.get("任务数")) + 1
        bucket["点击"] = _safe_int(bucket.get("点击")) + _safe_int(item.get("本平台点击"))
        bucket["订单"] = _safe_int(bucket.get("订单")) + _safe_int(item.get("本平台订单"))
        bucket["分佣"] = round(_safe_float(bucket.get("分佣")) + _safe_float(item.get("本平台分佣")), 2)
    rows = list(buckets.values())
    rows.sort(
        key=lambda item: (
            -_safe_int(item.get("点击")),
            -_safe_float(item.get("分佣")),
            -_safe_int(item.get("任务数")),
            str(item.get("剧场") or ""),
        )
    )
    return rows


def _filter_my_task_rows_by_window(task_rows: list[dict[str, object]], window_start: str, window_end: str) -> list[dict[str, object]]:
    start_day = str(window_start or "")[:10]
    end_day = str(window_end or "")[:10]
    if not start_day or not end_day:
        return list(task_rows)
    filtered: list[dict[str, object]] = []
    for item in task_rows:
        active_day = str(item.get("推广时间") or "")[:10]
        if start_day <= active_day <= end_day:
            filtered.append(item)
    return filtered


def _build_publish_analysis_lookup(
    db: FlywheelSQLite,
    *,
    published_from: str,
    published_to: str,
    platform: str,
) -> dict[str, dict[tuple[str, ...], dict[str, object]]]:
    rows = [
        dict(row)
        for row in db.list_publish_analysis_context_rows(
            published_from=published_from,
            published_to=published_to,
            platform=platform,
        )
    ]
    by_post_id: dict[tuple[str, str], dict[str, object]] = {}
    by_team_task: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        normalized_platform = str(row.get("platform") or "").strip().upper()
        post_id = str(row.get("platform_post_id") or "").strip()
        if normalized_platform and post_id and (normalized_platform, post_id) not in by_post_id:
            by_post_id[(normalized_platform, post_id)] = row
        team_id = str(row.get("team_id") or "").strip()
        task_id = str(row.get("task_id") or "").strip()
        if normalized_platform and team_id and task_id and (normalized_platform, team_id, task_id) not in by_team_task:
            by_team_task[(normalized_platform, team_id, task_id)] = row
    return {"by_post_id": by_post_id, "by_team_task": by_team_task}


def _match_analysis_context(
    item: dict[str, object],
    lookup: dict[str, dict[tuple[str, ...], dict[str, object]]],
) -> dict[str, object]:
    platform = str(item.get("social_type") or item.get("platform") or "").strip().upper()
    post_id = str(item.get("post_id") or item.get("id") or "").strip()
    if platform and post_id:
        matched = (lookup.get("by_post_id") or {}).get((platform, post_id))
        if matched:
            return matched
    team_id = str(item.get("team_id") or "").strip()
    task_id = str(item.get("task_id") or "").strip()
    if platform and team_id and task_id:
        matched = (lookup.get("by_team_task") or {}).get((platform, team_id, task_id))
        if matched:
            return matched
    return {}


def _metric_bucket(name: str) -> dict[str, object]:
    return {
        "名称": name,
        "帖子数": 0,
        "播放量": 0,
        "互动量": 0,
        "收益": 0.0,
        "互动率": "0.00%",
        "单条收益": 0.0,
        "千次播放收益": 0.0,
    }


def _update_metric_bucket(bucket: dict[str, object], *, views: int, interactions: int, revenue: float) -> None:
    bucket["帖子数"] = _safe_int(bucket.get("帖子数")) + 1
    bucket["播放量"] = _safe_int(bucket.get("播放量")) + views
    bucket["互动量"] = _safe_int(bucket.get("互动量")) + interactions
    bucket["收益"] = _safe_float(bucket.get("收益")) + revenue


def _finalize_metric_bucket(bucket: dict[str, object]) -> dict[str, object]:
    posts = max(1, _safe_int(bucket.get("帖子数")))
    views = _safe_int(bucket.get("播放量"))
    interactions = _safe_int(bucket.get("互动量"))
    revenue = _safe_float(bucket.get("收益"))
    bucket["收益"] = round(revenue, 2)
    bucket["单条收益"] = round(revenue / posts, 2)
    bucket["互动率"] = f"{(interactions / views * 100):.2f}%" if views > 0 else "0.00%"
    bucket["千次播放收益"] = round(revenue * 1000 / views, 2) if views > 0 else 0.0
    return bucket


def _percent_text_to_float(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _sorted_metric_buckets(buckets: dict[str, dict[str, object]], *, limit: int) -> list[dict[str, object]]:
    rows = [_finalize_metric_bucket(dict(bucket)) for bucket in buckets.values()]
    has_revenue_signal = any(_safe_float(item.get("收益")) > 0 for item in rows)
    if has_revenue_signal:
        rows.sort(
            key=lambda item: (
                -_safe_float(item.get("收益")),
                -_safe_float(item.get("千次播放收益")),
                -_safe_int(item.get("播放量")),
                -_safe_int(item.get("互动量")),
                str(item.get("名称") or ""),
            )
        )
    else:
        rows.sort(
            key=lambda item: (
                -_safe_int(item.get("播放量")),
                -_safe_int(item.get("互动量")),
                -_percent_text_to_float(item.get("互动率")),
                -_safe_int(item.get("帖子数")),
                str(item.get("名称") or ""),
            )
        )
    return rows[:limit]


def _analysis_novel_signature_set(rows: list[dict[str, object]]) -> set[str]:
    signatures: set[str] = set()
    for item in rows:
        for value in (item.get("平台应用"), item.get("剧场")):
            text = str(value or "").strip().lower()
            if text:
                signatures.add(text)
    signatures.update(
        {
            "novelmaster",
            "plotnovel",
            "novelshort",
            "webnovel",
            "moboreader",
            "motonovel",
            "novelgo",
            "webfic",
            "#novel",
            "#storytime",
        }
    )
    return signatures


def _analysis_item_is_novel(
    item: dict[str, object],
    *,
    matched: dict[str, object],
    novel_signatures: set[str],
) -> bool:
    if matched and str(matched.get("drama_title") or "").strip():
        return False
    blob = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("text") or ""),
            str(item.get("media_urls") or ""),
        ]
    ).lower()
    if any(signature and signature in blob for signature in novel_signatures):
        return True
    return False


def _empty_content_overview() -> dict[str, object]:
    return {
        "当日发布视频总数": 0,
        "当日发布成功数": 0,
        "覆盖账号数": 0,
        "当日推广链接点击次数": 0,
        "订单数": 0,
        "订单金额": 0.0,
        "广告金额": 0.0,
        "分佣金额": 0.0,
        "总收益": 0.0,
        "总播放量": 0,
        "点赞数": 0,
        "评论数": 0,
        "分享数": 0,
        "总互动量": 0,
        "整体互动率": "0.00%",
        "千次播放收益": 0.0,
        "接口总条数": 0,
        "实际分析条数": 0,
        "覆盖平台数": 0,
        "平均单条播放": 0.0,
        "平均单条收益": 0.0,
    }


def _finalize_content_overview(
    bucket: dict[str, object],
    *,
    clicks: int,
    orders: int,
    order_amount: float,
    ad_amount: float,
    share_amount: float,
) -> dict[str, object]:
    total_posts = _safe_int(bucket.get("当日发布视频总数"))
    total_views = _safe_int(bucket.get("总播放量"))
    total_likes = _safe_int(bucket.get("点赞数"))
    total_comments = _safe_int(bucket.get("评论数"))
    total_shares = _safe_int(bucket.get("分享数"))
    total_interaction = total_likes + total_comments + total_shares
    total_revenue = round(_safe_float(bucket.get("总收益")), 2)
    avg_views = round(total_views / total_posts, 2) if total_posts > 0 else 0.0
    avg_revenue = round(total_revenue / total_posts, 2) if total_posts > 0 else 0.0
    return {
        "当日发布视频总数": total_posts,
        "当日发布成功数": _safe_int(bucket.get("当日发布成功数")),
        "覆盖账号数": len(bucket.get("账号集合") or []),
        "当日推广链接点击次数": clicks,
        "订单数": orders,
        "订单金额": round(order_amount, 2),
        "广告金额": round(ad_amount, 2),
        "分佣金额": round(share_amount, 2),
        "总收益": total_revenue,
        "总播放量": total_views,
        "点赞数": total_likes,
        "评论数": total_comments,
        "分享数": total_shares,
        "总互动量": total_interaction,
        "整体互动率": f"{(total_interaction / total_views * 100):.2f}%" if total_views > 0 else "0.00%",
        "千次播放收益": round(total_revenue * 1000 / total_views, 2) if total_views > 0 else 0.0,
        "接口总条数": total_posts,
        "实际分析条数": total_posts,
        "覆盖平台数": len(bucket.get("平台集合") or []),
        "平均单条播放": avg_views,
        "平均单条收益": avg_revenue,
    }


def _build_publish_analysis_report(
    *,
    items: list[dict[str, object]],
    analysis_summary: dict[str, object],
    publish_record_summary: dict[str, object],
    income_daily_summary: dict[str, object],
    my_task_summary: dict[str, object],
    novel_task_summary: dict[str, object],
    window_start: str,
    window_end: str,
    lag_days: int,
    platform_label: str,
    normalized_platform: str,
    snapshot_day: int,
    db: FlywheelSQLite,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    report_day = str(window_end or "")[:10]
    drama_execution = _summarize_drama_execution(report_day)
    novel_execution = _summarize_novel_execution(report_day)
    lookup = _build_publish_analysis_lookup(
        db,
        published_from=window_start,
        published_to=window_end,
        platform=normalized_platform,
    )
    my_task_overview = my_task_summary.get("overview") if isinstance(my_task_summary.get("overview"), dict) else {}
    my_task_dimension = my_task_summary.get("dimension") if isinstance(my_task_summary.get("dimension"), list) else []
    novel_task_overview = novel_task_summary.get("overview") if isinstance(novel_task_summary.get("overview"), dict) else {}
    novel_task_dimension = novel_task_summary.get("dimension") if isinstance(novel_task_summary.get("dimension"), list) else []
    novel_signatures = _analysis_novel_signature_set(novel_task_dimension)
    account_buckets: dict[str, dict[str, object]] = {}
    platform_buckets: dict[str, dict[str, object]] = {}
    theater_buckets: dict[str, dict[str, object]] = {}
    drama_buckets: dict[str, dict[str, object]] = {}
    drama_content_bucket = _empty_content_overview() | {"账号集合": set(), "平台集合": set()}
    novel_content_bucket = _empty_content_overview() | {"账号集合": set(), "平台集合": set()}
    snapshot_rows: list[dict[str, object]] = []
    matched_count = 0

    for item in items:
        views = _safe_int(item.get("views"))
        likes = _safe_int(item.get("likes"))
        comments = _safe_int(item.get("comments"))
        shares = _safe_int(item.get("shares"))
        revenue = _safe_float(item.get("order_amount"))
        interactions = likes + comments + shares
        account_name = str(item.get("social_name") or "未知账号").strip() or "未知账号"
        platform_name = _platform_label(str(item.get("social_type") or item.get("platform") or "")) or "未知平台"
        matched = _match_analysis_context(item, lookup)
        is_novel_item = _analysis_item_is_novel(item, matched=matched, novel_signatures=novel_signatures)
        theater_name = _app_label(str(matched.get("drama_app_id") or "")) if matched else ""
        drama_name = str(matched.get("drama_title") or "").strip() if matched else ""
        content_bucket = novel_content_bucket if is_novel_item else drama_content_bucket
        content_bucket["当日发布视频总数"] = _safe_int(content_bucket.get("当日发布视频总数")) + 1
        if str(item.get("status") or "").upper() == "POSTED":
            content_bucket["当日发布成功数"] = _safe_int(content_bucket.get("当日发布成功数")) + 1
        content_bucket["总收益"] = round(_safe_float(content_bucket.get("总收益")) + revenue, 2)
        content_bucket["总播放量"] = _safe_int(content_bucket.get("总播放量")) + views
        content_bucket["点赞数"] = _safe_int(content_bucket.get("点赞数")) + likes
        content_bucket["评论数"] = _safe_int(content_bucket.get("评论数")) + comments
        content_bucket["分享数"] = _safe_int(content_bucket.get("分享数")) + shares
        account_set = content_bucket.get("账号集合")
        if isinstance(account_set, set):
            account_set.add(account_name)
        platform_set = content_bucket.get("平台集合")
        if isinstance(platform_set, set):
            platform_set.add(platform_name)

        _update_metric_bucket(account_buckets.setdefault(account_name, _metric_bucket(account_name)), views=views, interactions=interactions, revenue=revenue)
        _update_metric_bucket(platform_buckets.setdefault(platform_name, _metric_bucket(platform_name)), views=views, interactions=interactions, revenue=revenue)

        if theater_name:
            _update_metric_bucket(theater_buckets.setdefault(theater_name, _metric_bucket(theater_name)), views=views, interactions=interactions, revenue=revenue)
        if drama_name:
            _update_metric_bucket(drama_buckets.setdefault(drama_name, _metric_bucket(drama_name)), views=views, interactions=interactions, revenue=revenue)

        if matched:
            matched_count += 1
            if matched.get("publish_record_id") is not None:
                snapshot_rows.append(
                    {
                        "publish_record_id": matched.get("publish_record_id"),
                        "snapshot_day": snapshot_day,
                        "views": views,
                        "likes": likes,
                        "comments": comments,
                        "shares": shares,
                        "revenue": revenue,
                        "raw_payload": {
                            "analysis_item": item,
                            "matched_context": matched,
                        },
                    }
                )

    total_posts = len(items)
    total_count = _safe_int(analysis_summary.get("total_count")) or total_posts
    total_views = _safe_int(analysis_summary.get("view"))
    total_likes = sum(_safe_int(item.get("likes")) for item in items)
    total_comments = sum(_safe_int(item.get("comments")) for item in items)
    total_shares = sum(_safe_int(item.get("shares")) for item in items)
    total_interaction = _safe_int(analysis_summary.get("interaction"))
    if total_interaction <= 0:
        total_interaction = total_likes + total_comments + total_shares
    total_revenue = round(_safe_float(analysis_summary.get("order_amount")), 2)
    avg_views = round(total_views / total_posts, 2) if total_posts > 0 else 0.0
    avg_revenue = round(total_revenue / total_posts, 2) if total_posts > 0 else 0.0
    interaction_rate = f"{(total_interaction / total_views * 100):.2f}%" if total_views > 0 else "0.00%"
    revenue_per_mille = round(total_revenue * 1000 / total_views, 2) if total_views > 0 else 0.0
    match_rate = f"{(matched_count / total_posts * 100):.2f}%" if total_posts > 0 else "0.00%"

    account_dimension = _sorted_metric_buckets(account_buckets, limit=15)
    platform_dimension = _sorted_metric_buckets(platform_buckets, limit=8)
    theater_dimension = _sorted_metric_buckets(theater_buckets, limit=12)
    drama_dimension = _sorted_metric_buckets(drama_buckets, limit=15)
    daily_my_task_rows = _filter_my_task_rows_by_window(my_task_dimension, window_start, window_end)
    daily_novel_task_rows = _filter_my_task_rows_by_window(novel_task_dimension, window_start, window_end)
    my_task_theater_rows = _summarize_my_task_theaters(my_task_dimension)
    daily_my_task_theater_rows = _summarize_my_task_theaters(daily_my_task_rows)

    anomaly_rows = [
        {
            "账号": item.get("名称"),
            "平台": "",
            "帖子数": item.get("帖子数"),
            "播放量": item.get("播放量"),
            "收益": item.get("收益"),
            "说明": "连续多条内容播放偏低，优先检查账号健康度或授权状态",
        }
        for item in account_dimension
        if _safe_int(item.get("帖子数")) >= 2 and _safe_int(item.get("播放量")) == 0
    ]

    suggestions: list[str] = []
    if total_posts < total_count:
        suggestions.append(f"当前只分析了 {total_posts}/{total_count} 条记录，若要做完整策略判断，建议提高分页抓取范围后再看结论。")
    if matched_count < max(5, int(total_posts * 0.6)):
        suggestions.append(
            f"当前发布分析里的剧场/短剧匹配率仅 {match_rate}，先不要直接用这部分数据去大改短剧主链路；"
            "现阶段更适合把发布分析继续用于账号健康度和平台整体表现判断。"
        )
    task_total = len(daily_my_task_rows)
    task_active = sum(1 for item in daily_my_task_rows if _safe_int(item.get("本平台点击")) > 0)
    task_clicks = sum(_safe_int(item.get("本平台点击")) for item in daily_my_task_rows)
    task_orders = sum(_safe_int(item.get("本平台订单")) for item in daily_my_task_rows)
    task_order_amount = round(sum(_safe_float(item.get("本平台充值金额")) for item in daily_my_task_rows), 2)
    task_ad_amount = round(sum(_safe_float(item.get("本平台广告金额")) for item in daily_my_task_rows), 2)
    task_share = round(sum(_safe_float(item.get("本平台分佣")) for item in daily_my_task_rows), 2)
    novel_task_total = len(daily_novel_task_rows)
    novel_task_active = sum(1 for item in daily_novel_task_rows if _safe_int(item.get("本平台点击")) > 0)
    novel_task_clicks = sum(_safe_int(item.get("本平台点击")) for item in daily_novel_task_rows)
    novel_task_orders = sum(_safe_int(item.get("本平台订单")) for item in daily_novel_task_rows)
    novel_task_order_amount = round(sum(_safe_float(item.get("本平台充值金额")) for item in daily_novel_task_rows), 2)
    novel_task_ad_amount = round(sum(_safe_float(item.get("本平台广告金额")) for item in daily_novel_task_rows), 2)
    novel_task_share = round(sum(_safe_float(item.get("本平台分佣")) for item in daily_novel_task_rows), 2)
    drama_task_summary = {
        "任务数": task_total,
        "有点击任务数": task_active,
        "点击数": task_clicks,
        "订单数": task_orders,
        "订单金额": task_order_amount,
        "广告金额": task_ad_amount,
        "分佣金额": task_share,
        "有数据任务数": _safe_int(my_task_overview.get("当前平台有数据任务数")),
    }
    novel_task_summary_window = {
        "任务数": novel_task_total,
        "有点击任务数": novel_task_active,
        "点击数": novel_task_clicks,
        "订单数": novel_task_orders,
        "订单金额": novel_task_order_amount,
        "广告金额": novel_task_ad_amount,
        "分佣金额": novel_task_share,
        "有数据任务数": _safe_int(novel_task_overview.get("当前平台有数据任务数")),
    }
    drama_overview = _finalize_content_overview(
        drama_content_bucket,
        clicks=task_clicks,
        orders=task_orders,
        order_amount=task_order_amount,
        ad_amount=task_ad_amount,
        share_amount=task_share,
    )
    novel_overview = _finalize_content_overview(
        novel_content_bucket,
        clicks=novel_task_clicks,
        orders=novel_task_orders,
        order_amount=novel_task_order_amount,
        ad_amount=novel_task_ad_amount,
        share_amount=novel_task_share,
    )
    drama_execution_overview = drama_execution.get("overview") if isinstance(drama_execution.get("overview"), dict) else {}
    novel_execution_overview = novel_execution.get("overview") if isinstance(novel_execution.get("overview"), dict) else {}
    drama_overview.update(
        {
            "日期": drama_execution_overview.get("日期") or report_day,
            "轮次": drama_execution_overview.get("轮次") or 0,
            "模式": drama_execution_overview.get("模式") or "短剧 loop",
            "任务数": drama_execution_overview.get("任务数") or 0,
            "发布成功条数": drama_execution_overview.get("发布成功条数") or 0,
            "发布失败条数": drama_execution_overview.get("发布失败条数") or 0,
            "上传失败条数": drama_execution_overview.get("上传失败条数") or 0,
            "失败账号数": drama_execution_overview.get("失败账号数") or 0,
            "发布失败账号数": drama_execution_overview.get("发布失败账号数") or 0,
            "失败账号": drama_execution_overview.get("失败账号") or "-",
            "发布失败账号": drama_execution_overview.get("发布失败账号") or "-",
            "剪辑下载均耗": drama_execution_overview.get("剪辑下载均耗") or "-",
            "原视频均长": drama_execution_overview.get("原视频均长") or "-",
            "原视频时长缺失数": drama_execution_overview.get("原视频时长缺失数") or 0,
            "输出片段均长": drama_execution_overview.get("输出片段均长") or "-",
            "成片探测均长": drama_execution_overview.get("成片探测均长") or "-",
            "剪辑工具分布": drama_execution_overview.get("剪辑工具分布") or "-",
            "剪辑方式分布": drama_execution_overview.get("剪辑方式分布") or "-",
            "去重方式分布": drama_execution_overview.get("去重方式分布") or "-",
        }
    )
    novel_overview.update(
        {
            "日期": novel_execution_overview.get("日期") or report_day,
            "轮次": novel_execution_overview.get("轮次") or 0,
            "模式": novel_execution_overview.get("模式") or "小说 loop",
            "任务数": novel_execution_overview.get("任务数") or 0,
            "发布成功条数": novel_execution_overview.get("发布成功条数") or 0,
            "发布失败条数": novel_execution_overview.get("发布失败条数") or 0,
            "上传失败条数": novel_execution_overview.get("上传失败条数") or 0,
            "失败账号数": novel_execution_overview.get("失败账号数") or 0,
            "发布失败账号数": novel_execution_overview.get("发布失败账号数") or 0,
            "失败账号": novel_execution_overview.get("失败账号") or "-",
            "发布失败账号": novel_execution_overview.get("发布失败账号") or "-",
            "剪辑下载均耗": novel_execution_overview.get("剪辑下载均耗") or "-",
            "原视频均长": novel_execution_overview.get("原视频均长") or "-",
            "原视频时长缺失数": novel_execution_overview.get("原视频时长缺失数") or "-",
            "输出片段均长": novel_execution_overview.get("输出片段均长") or "-",
            "成片探测均长": novel_execution_overview.get("成片探测均长") or "-",
            "剪辑工具分布": novel_execution_overview.get("剪辑工具分布") or "-",
            "剪辑方式分布": novel_execution_overview.get("剪辑方式分布") or "-",
            "去重方式分布": novel_execution_overview.get("去重方式分布") or "-",
        }
    )
    publish_total = _safe_int(publish_record_summary.get("当日发布视频总数"))
    publish_success = _safe_int(publish_record_summary.get("当日发布成功数"))
    if task_total > 0:
        active_rate = task_active / max(1, task_total)
        if active_rate < 0.6:
            suggestions.append(
                f"当前平台有数据任务占比仅 {active_rate * 100:.1f}%（{task_active}/{task_total}），说明现有“全剧场混池随机发”能跑通，但命中有效任务的比例不高；"
                "更稳的调整是给自动选剧增加一层“优先已在我的任务且当前平台已有点击数据”的软加权，而不是改成只发少数固定剧。"
            )
    if task_clicks >= 200 and task_orders == 0:
        suggestions.append(
            f"当前平台已有 {task_clicks} 次点击但仍是 0 订单、0 充值，说明现阶段不适合按收益改剪辑手法池；"
            "先保持现有随机剪辑/随机去重功能不动，把 Facebook 的优化重点放在剧场软权重、推广文案、推广链接承接和账号健康度上。"
        )
    theater_reference_rows = daily_my_task_theater_rows or my_task_theater_rows
    if theater_reference_rows:
        top_theaters = theater_reference_rows[:3]
        theater_text = "、".join(
            f"{row.get('剧场')}（点击 {row.get('点击')}）"
            for row in top_theaters
            if str(row.get("剧场") or "").strip()
        )
        if theater_text:
            suggestions.append(
                f"从“我的短剧任务”看，Facebook 当前更有点击反馈的剧场主要是 {theater_text}；"
                "因此建议保留现有多剧场混池，但在 Facebook 批量任务里对这些剧场做轻度加权，弱化完全平均随机。"
            )
    if novel_task_total > 0:
        suggestions.append(
            f"小说任务窗口内共 {novel_task_total} 条，其中有点击 {novel_task_active} 条，累计点击 {novel_task_clicks}、订单 {novel_task_orders}、分佣 {round(novel_task_share, 2)}；"
            "建议把小说和短剧分开观察，不要直接用短剧的点击/收益阈值去调小说生成策略。"
        )
    if theater_dimension and _safe_float(theater_dimension[0].get("单条收益")) > max(0.0, avg_revenue * 1.3):
        suggestions.append(f"{theater_dimension[0].get('名称')} 的单条收益明显高于整体均值，可在自动选剧时做轻度加权，但先不要破坏现有随机混池主逻辑。")
    if any(_safe_int(item.get("帖子数")) >= 3 and _safe_float(item.get("单条收益")) <= max(0.01, avg_revenue * 0.5) for item in theater_dimension):
        suggestions.append("部分剧场最近样本多但收益偏弱，建议先轻度降权或拉长冷却，不建议直接移出候选池。")
    if anomaly_rows:
        suggestions.append("存在连续低播放账号，优先排查账号健康度、平台权限和授权状态，再判断是否需要改内容策略。")
    if task_share <= 0.1 and task_orders == 0:
        suggestions.append(
            "当前还没有足够的订单/分佣信号支持“按收益动态改剪辑手法、去重手法或时长”，"
            "所以现有剪辑层先维持随机差异化即可，等后面把发布结果和短剧映射补齐后，再做内容层策略优化更稳。"
        )
    if not suggestions:
        suggestions.append("当前没有必须立刻修改主链路的强信号，建议继续保持现有候选召回 + 规则过滤 + 轻随机主逻辑。")

    failure_summary = _analysis_failure_summary_lines(
        drama_overview,
        drama_execution.get("failure_reason_rows") if isinstance(drama_execution.get("failure_reason_rows"), list) else [],
        drama_execution.get("failure_details") if isinstance(drama_execution.get("failure_details"), list) else [],
        novel_overview,
        novel_execution.get("failure_reason_rows") if isinstance(novel_execution.get("failure_reason_rows"), list) else [],
        novel_execution.get("failure_details") if isinstance(novel_execution.get("failure_details"), list) else [],
    )
    failure_summary_suffix = ""
    if failure_summary:
        failure_summary_suffix = (
            f" 另有失败情况：短剧发布失败 {drama_overview.get('发布失败条数') or 0} 条、上传失败 {drama_overview.get('上传失败条数') or 0} 条；"
            f"小说发布失败 {novel_overview.get('发布失败条数') or 0} 条、上传失败 {novel_overview.get('上传失败条数') or 0} 条。"
        )

    report = {
        "执行模式": "发布数据分析日报",
        "目标平台": platform_label,
        "统计窗口": f"{window_start[:10]} 至 {window_end[:10]}",
        "数据延迟说明": f"平台数据通常延迟 1-2 天，当前按滞后 {lag_days} 天窗口统计",
        "结论摘要": (
            f"本次发布记录共 {publish_total} 条，成功 {publish_success} 条；"
            f"分析接口实际回传 {total_posts} 条内容，覆盖 {len(account_buckets)} 个账号、{len(platform_buckets)} 个平台，"
            f"短剧任务点击 {task_clicks}、订单 {task_orders}、订单金额 {task_order_amount}、广告金额 {task_ad_amount}、分佣金额 {round(task_share, 2)}；"
            f"小说任务点击 {novel_task_clicks}、订单 {novel_task_orders}、订单金额 {novel_task_order_amount}、广告金额 {novel_task_ad_amount}、分佣金额 {round(novel_task_share, 2)}；"
            f"点赞 {total_likes}、评论 {total_comments}、分享 {total_shares}，剧场/短剧维度匹配率 {match_rate}。"
            f"{failure_summary_suffix}"
        ),
        "总体概览": {
            "当日发布视频总数": publish_total,
            "当日发布成功数": publish_success,
            "接口总条数": total_count,
            "实际分析条数": total_posts,
            "覆盖账号数": len(account_buckets),
            "覆盖平台数": len(platform_buckets),
            "当日推广链接点击次数": task_clicks,
            "推广链接点击次数": task_clicks,
            "订单数": task_orders,
            "订单金额": task_order_amount,
            "广告金额": task_ad_amount,
            "分佣金额": task_share,
            "小说任务数": novel_task_total,
            "小说有点击任务数": novel_task_active,
            "小说点击数": novel_task_clicks,
            "小说订单数": novel_task_orders,
            "小说订单金额": novel_task_order_amount,
            "小说广告金额": novel_task_ad_amount,
            "小说分佣金额": novel_task_share,
            "总收益": round(_safe_float(income_daily_summary.get("总收益")), 2),
            "总播放量": total_views,
            "点赞数": total_likes,
            "评论数": total_comments,
            "分享数": total_shares,
            "总互动量": total_interaction,
            "平均单条播放": avg_views,
            "平均单条收益": avg_revenue,
            "整体互动率": interaction_rate,
            "千次播放收益": revenue_per_mille,
            "剧场短剧匹配率": match_rate,
        },
        "短剧总体概览": drama_overview,
        "小说总体概览": novel_overview,
        "短剧执行概览": drama_execution.get("overview") or {},
        "小说执行概览": novel_execution.get("overview") or {},
        "短剧剪辑下载耗时明细": drama_execution.get("timing_rows") or [],
        "小说剪辑下载耗时明细": novel_execution.get("timing_rows") or [],
        "短剧失败原因分布": drama_execution.get("failure_reason_rows") or [],
        "小说失败原因分布": novel_execution.get("failure_reason_rows") or [],
        "短剧失败账号明细": drama_execution.get("failure_details") or [],
        "小说失败账号明细": novel_execution.get("failure_details") or [],
        "失败情况总结": failure_summary,
        "短剧任务概览": drama_task_summary,
        "小说任务概览": novel_task_summary_window,
        "账号维度": account_dimension,
        "平台维度": platform_dimension,
        "剧场维度": theater_dimension,
        "短剧维度": drama_dimension,
        "我的短剧任务概览": my_task_overview,
        "我的短剧任务维度": my_task_dimension,
        "我的小说任务概览": novel_task_overview,
        "我的小说任务维度": novel_task_dimension,
        "异常账号": anomaly_rows,
        "建议": suggestions,
        "已写入快照数": len(snapshot_rows),
    }
    return report, snapshot_rows


def cmd_publish_analysis_daily(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    db = FlywheelSQLite(Path(config.database_path))
    db.init_schema(schema_path())

    today = datetime.now().date()
    end_day = today - timedelta(days=max(0, int(args.lag_days)))
    start_day = end_day - timedelta(days=max(0, int(args.window_days) - 1))
    start_date = f"{start_day.isoformat()} 00:00:00"
    end_date = f"{end_day.isoformat()} 23:59:59"
    normalized_platform = normalize_publish_platform(args.platform) if str(args.platform or "").strip() else ""

    analysis_summary = _fetch_all_publish_analysis(
        platform=normalized_platform,
        social_id=str(args.social_id or "").strip(),
        start_date=start_date,
        end_date=end_date,
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    publish_record_summary = _fetch_publish_record_summary(
        platform=normalized_platform,
        social_id=str(args.social_id or "").strip(),
        start_date=start_date,
        end_date=end_date,
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    income_daily_summary = _fetch_income_daily_summary(
        platform=normalized_platform,
        start_date=start_date,
        end_date=end_date,
    )
    language_map, app_map = _load_creator_enum_maps("1")
    novel_language_map, novel_app_map = _load_creator_enum_maps("2")
    my_task_rows = _fetch_all_my_task_rows(
        task_type="1",
        page_size=max(20, int(args.page_size)),
        max_pages=max(1, int(args.max_pages)),
    )
    novel_task_rows = _fetch_all_my_task_rows(
        task_type="2",
        page_size=max(20, int(args.page_size)),
        max_pages=max(1, int(args.max_pages)),
    )
    my_task_overview, my_task_dimension = _build_my_task_dimension(
        task_rows=my_task_rows.get("items") if isinstance(my_task_rows.get("items"), list) else [],
        normalized_platform=normalized_platform,
        language_map=language_map,
        app_map=app_map,
    )
    novel_task_overview, novel_task_dimension = _build_my_novel_task_dimension(
        task_rows=novel_task_rows.get("items") if isinstance(novel_task_rows.get("items"), list) else [],
        normalized_platform=normalized_platform,
        language_map=novel_language_map,
        app_map=novel_app_map,
    )
    report_zh, snapshot_rows = _build_publish_analysis_report(
        items=analysis_summary.get("items") if isinstance(analysis_summary.get("items"), list) else [],
        analysis_summary=analysis_summary,
        publish_record_summary=publish_record_summary,
        income_daily_summary=income_daily_summary,
        my_task_summary={
            "overview": my_task_overview,
            "dimension": my_task_dimension,
            "total_count": my_task_rows.get("total_count"),
        },
        novel_task_summary={
            "overview": novel_task_overview,
            "dimension": novel_task_dimension,
            "total_count": novel_task_rows.get("total_count"),
        },
        window_start=start_date,
        window_end=end_date,
        lag_days=int(args.lag_days),
        platform_label=_platform_label(normalized_platform) if normalized_platform else "全部平台",
        normalized_platform=normalized_platform,
        snapshot_day=int(datetime.now().strftime("%Y%m%d")),
        db=db,
    )
    written_snapshot_count = db.upsert_metrics_snapshots(snapshot_rows) if args.write_snapshot else 0
    payload = {
        "status": "ok",
        "mode": "publish_analysis_daily",
        "analysis_window": {
            "start_date": start_date,
            "end_date": end_date,
            "lag_days": int(args.lag_days),
            "window_days": int(args.window_days),
        },
        "analysis_source_summary": analysis_summary,
        "publish_record_summary": publish_record_summary,
        "income_daily_summary": income_daily_summary,
        "report_zh": report_zh,
        "user_summary_zh": str(report_zh.get("结论摘要") or "").strip(),
        "written_snapshot_count": written_snapshot_count,
    }
    payload = _finalize_payload(payload)
    try:
        payload.update(_maybe_push_feishu_analysis_report(payload))
    except Exception as exc:
        payload["feishu_push"] = {"enabled": True, "error": str(exc)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_failed_publish_items() -> tuple[dict, list[dict], str]:
    state = _get_failed_publish_state()
    items = state.get("items") if isinstance(state.get("items"), list) else []
    platform = str(state.get("platform") or "").strip()
    if not items or not platform:
        raise SystemExit("当前没有待处理的失败发布任务。")
    return state, [dict(item) for item in items], platform


def _retry_failed_publish_summary_zh(report: dict) -> str:
    base = _batch_user_summary_zh(report)
    if not base:
        return "已对上次失败发布任务重试一次。"
    return "已对上次失败发布任务重试一次。\n" + base


def cmd_retry_failed_publish(args: argparse.Namespace) -> None:
    _, items, platform = _load_failed_publish_items()
    published_items, records = _publish_batch_with_retries(
        items,
        args,
        platform,
        max_attempts=1,
    )
    cleanup = {"deleted_paths": [], "errors": []}
    if not args.keep_output and records:
        successful_keys = {
            (str(record.get("team_id") or ""), str(record.get("task_id") or ""))
            for record in records
            if str(record.get("status") or "").upper() in SUCCESSFUL_PUBLISH_STATUSES
        }
        cleanup_paths: list[str] = []
        for item in published_items:
            tasks = ((item.get("publish") or {}).get("tasks")) or []
            if not tasks:
                continue
            if all((str(task.get("team_id") or ""), str(task.get("task_id") or "")) in successful_keys for task in tasks):
                clip = item.get("clip") or {}
                cleanup_paths.extend([str(clip.get("downloaded_file") or ""), str(clip.get("publish_ready_file") or "")])
        cleanup = _cleanup_generated_files(cleanup_paths)

    payload = {
        "status": "done",
        "mode": "retry_failed_publish",
        "platform": platform,
        "requested_count": len(items),
        "items": published_items,
        "publish_records": list(local_payload.get("publish_records") or records),
        "cleanup": {
            "enabled": not args.keep_output,
            **cleanup,
        },
    }
    payload = _settle_publish_report_payload(
        payload,
        platform=platform,
        wait_seconds=int(args.collect_wait_seconds),
        poll_interval=int(args.collect_poll_interval),
        settle_timeout_seconds=21600,
        report_builder=_batch_report_zh,
    )
    payload["report_zh"]["执行模式"] = "失败发布重试"
    payload["user_summary_zh"] = _retry_failed_publish_summary_zh(payload["report_zh"])
    payload["retry_prompt_zh"] = _failed_publish_prompt_zh(payload["report_zh"])
    failed_state = _failed_publish_state_payload(
        mode="retry_failed_publish",
        platform=platform,
        items=published_items,
        records=payload.get("publish_records") if isinstance(payload.get("publish_records"), list) else records,
    )
    _set_failed_publish_state(failed_state)
    payload = _finalize_payload(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_discard_failed_publish_output(args: argparse.Namespace) -> None:
    _, items, platform = _load_failed_publish_items()
    cleanup = _cleanup_generated_files(_failed_publish_clip_paths(items))
    _set_failed_publish_state(None)
    payload = {
        "status": "done",
        "mode": "discard_failed_publish_output",
        "platform": platform,
        "deleted_count": len(cleanup.get("deleted_paths", [])),
        "cleanup": cleanup,
        "user_summary_zh": (
            f"已删除 {len(cleanup.get('deleted_paths', []))} 个失败发布任务保留的本地成片。"
            if not cleanup.get("errors")
            else "已尝试删除失败发布任务保留的本地成片，但有部分删除失败。"
        ),
    }
    payload = _finalize_payload(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_show_failed_publish_paths(args: argparse.Namespace) -> None:
    state, _, _ = _load_failed_publish_items()
    payload = {
        "status": "ok",
        "mode": "show_failed_publish_paths",
        "report_zh": _failed_publish_paths_payload(state),
        "user_summary_zh": "以下是当前保留的失败任务成片路径。",
    }
    payload = _finalize_payload(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_cleanup_daily_artifacts(args: argparse.Namespace) -> None:
    payload = _cleanup_daily_artifacts()
    payload = _finalize_payload(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_import_accounts(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    db = FlywheelSQLite(Path(config.database_path))
    db.init_schema(schema_path())
    csv_path = Path(args.csv).expanduser().resolve()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    imported = db.import_accounts(rows)
    print(json.dumps({"status": "ok", "imported": imported, "csv": str(csv_path)}, ensure_ascii=False, indent=2))


def cmd_sync_publish_accounts(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    db = FlywheelSQLite(Path(config.database_path))
    db.init_schema(schema_path())
    rows = sync_publish_accounts(
        language=args.language,
        country=args.country,
        tier=args.tier,
        daily_post_limit=args.daily_post_limit,
    )
    synced = db.replace_accounts(rows)
    print(
        json.dumps(
            {
                "status": "ok",
                "synced": synced,
                "language": args.language,
                "country": args.country,
                "tier": args.tier,
                "daily_post_limit": args.daily_post_limit,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_list_accounts(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    db = FlywheelSQLite(Path(config.database_path))
    db.init_schema(schema_path())
    rows = [dict(row) for row in db.list_accounts()]
    print(json.dumps({"accounts": rows}, ensure_ascii=False, indent=2))


def cmd_show_round(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    db = FlywheelSQLite(Path(config.database_path))
    db.init_schema(schema_path())
    row = db.get_round(args.round_id)
    if row is None:
        raise SystemExit(f"Round {args.round_id} not found in {config.database_path}")
    stages = db.get_round_stages(args.round_id)
    parsed_stages = parse_stage_rows([dict(item) for item in stages])
    payload = {
        "round": dict(row),
        "stages": [dict(item) for item in stages],
        "mode": "show_round",
        "report_zh": build_round_report_zh(
            round_id=int(row["id"]),
            status=str(row["status"] or ""),
            stages=[
                dict(item.get("parsed_result_payload") or {})
                for item in parsed_stages
                if isinstance(item.get("parsed_result_payload"), dict)
            ],
            live_refresh=True,
        ),
    }
    payload["user_summary_zh"] = build_round_user_summary_zh(payload["report_zh"])
    payload = _finalize_payload(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Barry Video flywheel CLI")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to flywheel config")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="Initialize flywheel SQLite database")
    init_db.set_defaults(func=cmd_init_db)

    run_local = subparsers.add_parser("run-local", help="Clip and publish a local video without auto drama selection")
    run_local.add_argument("--file", required=True, help="Local video file path")
    run_local.add_argument(
        "--account-id",
        action="append",
        default=[],
        help="Publish account ID. Can be repeated.",
    )
    run_local.add_argument(
        "--team-id",
        action="append",
        default=[],
        help="Publish team_id. Can be repeated.",
    )
    run_local.add_argument(
        "--publish-platform",
        default=None,
        help="Target platform selected by the user, such as TIKTOK. Required for real publish.",
    )
    run_local.add_argument("--title", default="", help="Publish title. Defaults to the source file name.")
    run_local.add_argument("--text", default="", help="Publish caption. Defaults to the source file name.")
    run_local.add_argument("--text-file", default=None, help="Read publish caption from a UTF-8 file.")
    run_local.add_argument("--schedule-at", default=None, help="Optional scheduled publish time.")
    run_local.add_argument("--download-dir", default=None, help="Where to store the generated clip before publishing.")
    run_local.add_argument("--keep-output", action="store_true", help="Keep generated local clip after publish succeeds.")
    run_local.add_argument("--cut-type", choices=HIGH_CUT_CHOICES, default=DEFAULT_HIGH_CUT_CONFIG["cut_type"])
    run_local.add_argument("--duration", default=DEFAULT_HIGH_CUT_CONFIG["cut_duration"], help="Clip duration, defaults to auto.")
    run_local.add_argument("--output-count", type=int, default=DEFAULT_HIGH_CUT_CONFIG["output_count"])
    run_local.add_argument("--script-count", type=int, default=DEFAULT_HIGH_CUT_CONFIG["script_count"])
    run_local.add_argument(
        "--deduplication",
        nargs="*",
        choices=DEDUPLICATION_CHOICES,
        default=None,
        help="Deduplication methods.",
    )
    run_local.add_argument("--watermark", default=DEFAULT_HIGH_CUT_CONFIG["watermark"])
    run_local.add_argument("--merge-video", action="store_true")
    run_local.add_argument("--upload-timeout", type=int, default=300)
    run_local.add_argument("--submit-timeout", type=int, default=90)
    run_local.add_argument("--timeout", type=int, default=DEFAULT_TASK_TIMEOUT)
    run_local.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    run_local.add_argument(
        "--publish-concurrency",
        type=int,
        default=None,
        help="Parallel publishing task count. Omit to reuse flywheel runtime publish_execute_concurrency.",
    )
    run_local.add_argument(
        "--publish-retries",
        type=int,
        default=3,
        help="How many extra publish retries to run for failed/unsubmitted publish tasks after the first pass. Defaults to 3.",
    )
    run_local.add_argument("--collect-wait-seconds", type=int, default=180)
    run_local.add_argument("--collect-poll-interval", type=int, default=15)
    run_local.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    run_local.set_defaults(func=cmd_run_local)

    run_batch_drama = subparsers.add_parser(
        "run-batch-drama",
        help="Randomly select multiple dramas, clip in batch, publish each video to selected accounts, then collect status",
    )
    run_batch_mode = run_batch_drama.add_mutually_exclusive_group()
    run_batch_mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Only build the batch plan; do not clip or publish",
    )
    run_batch_mode.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="Run real clipping and publishing side effects",
    )
    run_batch_drama.set_defaults(dry_run=True)
    run_batch_drama.add_argument("--count", type=int, default=10, help="How many dramas/videos to plan")
    run_batch_drama.add_argument(
        "--publish-platform",
        required=True,
        help="Target publish platform selected by the user, such as FACEBOOK",
    )
    run_batch_drama.add_argument(
        "--account-id",
        action="append",
        default=[],
        help="Publish account ID selected by the user. Repeat for multiple accounts.",
    )
    run_batch_drama.add_argument(
        "--team-id",
        action="append",
        default=[],
        help="Publish team_id selected by the user. Repeat for multiple accounts.",
    )
    run_batch_drama.add_argument(
        "--allow-account-reuse",
        action="store_true",
        help="Allow reusing accounts when selected accounts are fewer than --count.",
    )
    run_batch_drama.add_argument("--drama-platform", default="", help="Optional drama app_id filter, such as dramabox")
    run_batch_drama.add_argument(
        "--language",
        default="",
        help="Optional drama language ID. Omit for all-language mixed candidate pool.",
    )
    run_batch_drama.add_argument("--drama-order", default="publish_at", help="Drama candidate order field")
    run_batch_drama.add_argument("--search", default="", help="Optional drama search keyword")
    run_batch_drama.add_argument(
        "--episode-order",
        type=int,
        default=None,
        help="Force a specific episode. Omit to use data-driven episode selection.",
    )
    run_batch_drama.add_argument(
        "--cut-type",
        choices=HIGH_CUT_CHOICES,
        default=None,
        help="Clip method. Omit to randomize methods across the batch.",
    )
    run_batch_drama.add_argument(
        "--duration",
        default=DEFAULT_HIGH_CUT_CONFIG["cut_duration"],
        help="Clip duration, defaults to auto.",
    )
    run_batch_drama.add_argument("--output-count", type=int, default=DEFAULT_HIGH_CUT_CONFIG["output_count"])
    run_batch_drama.add_argument("--script-count", type=int, default=DEFAULT_HIGH_CUT_CONFIG["script_count"])
    run_batch_drama.add_argument(
        "--deduplication",
        action="append",
        choices=DEDUPLICATION_CHOICES,
        default=None,
        help="Deduplication method pool. Repeat to rotate methods across batch items.",
    )
    run_batch_drama.add_argument("--watermark", default=DEFAULT_HIGH_CUT_CONFIG["watermark"])
    run_batch_drama.add_argument(
        "--clip-concurrency",
        type=int,
        default=None,
        help="Parallel clipping task count. Omit to reuse flywheel runtime clip_execute_concurrency.",
    )
    run_batch_drama.add_argument(
        "--source-prepare-retry-count",
        type=int,
        default=None,
        help="Extra retries for retryable source-prepare failures such as sketch timeout or SSL errors.",
    )
    run_batch_drama.add_argument(
        "--publish-concurrency",
        type=int,
        default=None,
        help="Parallel publishing task count. Omit to reuse flywheel runtime publish_execute_concurrency.",
    )
    run_batch_drama.add_argument(
        "--publish-retries",
        type=int,
        default=3,
        help="How many extra publish retries to run for failed/unsubmitted items after the first publish pass. Defaults to 3.",
    )
    run_batch_drama.add_argument("--download-dir", default=None, help="Where to store generated clips before publishing")
    run_batch_drama.add_argument("--keep-output", action="store_true", help="Keep generated local clips after publish succeeds")
    run_batch_drama.add_argument("--upload-timeout", type=int, default=300)
    run_batch_drama.add_argument("--submit-timeout", type=int, default=90)
    run_batch_drama.add_argument("--timeout", type=int, default=DEFAULT_TASK_TIMEOUT)
    run_batch_drama.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    run_batch_drama.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    run_batch_drama.add_argument("--collect-wait-seconds", type=int, default=180)
    run_batch_drama.add_argument("--collect-poll-interval", type=int, default=15)
    run_batch_drama.set_defaults(func=cmd_run_batch_drama)

    retry_failed_publish = subparsers.add_parser(
        "retry-failed-publish",
        help="Retry the last saved failed publish tasks once",
    )
    retry_failed_publish.add_argument("--publish-concurrency", type=int, default=1, help="Parallel publishing task count")
    retry_failed_publish.add_argument("--collect-wait-seconds", type=int, default=180)
    retry_failed_publish.add_argument("--collect-poll-interval", type=int, default=15)
    retry_failed_publish.add_argument("--keep-output", action="store_true", help="Keep generated local clips after retry succeeds")
    retry_failed_publish.add_argument("--publish-retries", type=int, default=0, help="Unused here; retry-failed-publish always retries once.")
    retry_failed_publish.set_defaults(func=cmd_retry_failed_publish)

    discard_failed_publish_output = subparsers.add_parser(
        "discard-failed-publish-output",
        help="Delete retained local clips for the last saved failed publish tasks",
    )
    discard_failed_publish_output.set_defaults(func=cmd_discard_failed_publish_output)

    show_failed_publish_paths = subparsers.add_parser(
        "show-failed-publish-paths",
        help="Show retained local clip paths for the last saved failed publish tasks",
    )
    show_failed_publish_paths.set_defaults(func=cmd_show_failed_publish_paths)

    cleanup_daily_artifacts = subparsers.add_parser(
        "cleanup-daily-artifacts",
        help="Delete retained failed publish clips and residual report files",
    )
    cleanup_daily_artifacts.set_defaults(func=cmd_cleanup_daily_artifacts)

    import_accounts = subparsers.add_parser("import-accounts", help="Import account CSV into flywheel DB")
    import_accounts.add_argument("--csv", required=True, help="Path to account csv")
    import_accounts.set_defaults(func=cmd_import_accounts)

    sync_accounts = subparsers.add_parser("sync-publish-accounts", help="Sync accounts from publish accounts API")
    sync_accounts.add_argument("--language", default="2", help="Default language to assign to synced accounts")
    sync_accounts.add_argument("--country", default="", help="Optional default country code")
    sync_accounts.add_argument("--tier", default="new", help="Default flywheel tier for synced accounts")
    sync_accounts.add_argument("--daily-post-limit", type=int, default=3, help="Default daily post limit")
    sync_accounts.set_defaults(func=cmd_sync_publish_accounts)

    publish_analysis_daily = subparsers.add_parser("publish-analysis-daily", help="拉取发布分析接口并输出每日中文分析报告")
    publish_analysis_daily.add_argument("--platform", default="", help="可选，只分析单个平台，如 FACEBOOK")
    publish_analysis_daily.add_argument("--social-id", default="", help="可选，只分析单个账号 social_id")
    publish_analysis_daily.add_argument("--window-days", type=int, default=1, help="统计窗口天数，默认 1，只统计滞后日期当天")
    publish_analysis_daily.add_argument("--lag-days", type=int, default=2, help="数据延迟天数，默认 2")
    publish_analysis_daily.add_argument("--page-size", type=int, default=100, help="每页拉取数量")
    publish_analysis_daily.add_argument("--max-pages", type=int, default=20, help="最多拉取页数")
    publish_analysis_daily.add_argument("--write-snapshot", action="store_true", help="将本次分析结果写回本地 metrics_snapshot")
    publish_analysis_daily.set_defaults(func=cmd_publish_analysis_daily)

    account = subparsers.add_parser("account", help="Account utilities")
    account_subparsers = account.add_subparsers(dest="account_command", required=True)
    account_list = account_subparsers.add_parser("list", help="List imported accounts")
    account_list.set_defaults(func=cmd_list_accounts)

    show_round = subparsers.add_parser("show-round", help="Show round detail")
    show_round.add_argument("round_id", type=int, help="Round id")
    show_round.set_defaults(func=cmd_show_round)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        payload = _build_failure_report_payload(args, "用户手动中断执行", status="interrupted")
        if payload:
            _finalize_payload(payload)
        raise
    except SystemExit as exc:
        code = exc.code
        if code not in (0, None):
            reason = str(code or "命令提前退出")
            payload = _build_failure_report_payload(args, reason, status="failed")
            if payload:
                _finalize_payload(payload)
        raise
    except Exception as exc:
        payload = _build_failure_report_payload(args, str(exc), status="failed")
        if payload:
            _finalize_payload(payload)
        raise


if __name__ == "__main__":
    main()
