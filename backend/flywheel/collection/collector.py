from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from inbeidou_cli import get_publish_records, require_success


RUNNING_PUBLISH_STATUSES = {"WAITING", "PENDING", "PROCESSING", "QUEUED", "SUBMITTED"}
SUCCESSFUL_PUBLISH_STATUSES = {"POSTED", "SUCCESS", "DONE"}
PROJECT_ROOT_DIR = Path(__file__).resolve().parents[3]
PROJECT_DELETE_ALLOWED_ROOTS = (
    PROJECT_ROOT_DIR / "data" / "flywheel" / "clipped",
    PROJECT_ROOT_DIR / "runtime",
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
    if resolved in {Path.home().resolve()}:
        return False, "拒绝删除用户目录"
    return True, ""


def _fetch_remote_records(*, platforms: list[str], max_pages: int, page_size: int) -> dict[tuple[str, str], dict[str, Any]]:
    remote_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for platform in platforms:
        for page in range(1, max_pages + 1):
            body = require_success(
                get_publish_records(page=page, page_size=page_size, social_type=platform),
                f"获取 {platform} 发布记录",
            )
            items = body.get("items") if isinstance(body.get("items"), list) else []
            if not items:
                break
            for item in items:
                key = (str(item.get("team_id") or ""), str(item.get("task_id") or ""))
                if key[0] and key[1]:
                    remote_by_key[key] = item
            page_info = body.get("page") or {}
            current_page = int(page_info.get("current_page") or page)
            total_count = int(page_info.get("total_count") or 0)
            if current_page * page_size >= total_count:
                break
    return remote_by_key


def _parse_raw_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _parse_clip_options(asset: dict[str, Any] | None) -> dict[str, Any]:
    raw = (asset or {}).get("clip_options")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _is_successfully_published(status: str) -> bool:
    return str(status or "").strip().upper() in SUCCESSFUL_PUBLISH_STATUSES


def _cleanup_local_publish_files(
    *,
    publish_records: list[dict[str, Any]],
    publish_plans: list[dict[str, Any]] | None,
    video_assets: list[dict[str, Any]] | None,
    remote_by_key: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    asset_by_id = {str(item.get("id") or ""): dict(item) for item in (video_assets or []) if str(item.get("id") or "")}
    plan_by_id = {str(item.get("id") or ""): dict(item) for item in (publish_plans or []) if str(item.get("id") or "")}
    asset_to_records: dict[str, list[dict[str, Any]]] = {}

    for record in publish_records:
        plan = plan_by_id.get(str(record.get("publish_plan_id") or ""))
        asset_id = str((plan or {}).get("video_asset_id") or "")
        if not asset_id:
            continue
        asset_to_records.setdefault(asset_id, []).append(record)

    cleanup_by_asset: dict[str, dict[str, Any]] = {}
    for asset_id, records in asset_to_records.items():
        statuses: list[str] = []
        publish_ready_paths: set[str] = set()
        for record in records:
            key = (str(record.get("team_id") or ""), str(record.get("task_id") or ""))
            matched = remote_by_key.get(key) or {}
            statuses.append(str(matched.get("status") or record.get("status") or ""))
            raw_payload = _parse_raw_payload(record.get("raw_payload"))
            publish_ready_path = str(raw_payload.get("publish_ready_path") or "").strip()
            if publish_ready_path:
                publish_ready_paths.add(publish_ready_path)

        if not statuses or not all(_is_successfully_published(status) for status in statuses):
            continue

        asset = asset_by_id.get(asset_id) or {}
        clipped_video_path = str(asset.get("clipped_video_path") or "").strip()
        deleted_paths: list[str] = []
        failed_paths: list[dict[str, str]] = []
        seen_paths: set[str] = set()
        candidate_paths = [clipped_video_path, *sorted(publish_ready_paths)]
        for candidate in candidate_paths:
            normalized = str(candidate or "").strip()
            if not normalized or normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            path = Path(normalized)
            if not path.exists():
                continue
            try:
                allowed, reason = _validate_cleanup_target(path)
                if not allowed:
                    failed_paths.append({"path": str(path), "error": reason})
                    continue
                path.unlink()
                deleted_paths.append(str(path))
            except OSError as exc:
                failed_paths.append({"path": str(path), "error": str(exc)})

        cleanup_by_asset[asset_id] = {
            "local_clip_cleanup_enabled": True,
            "local_clip_cleanup_status": "deleted" if not failed_paths else "delete_failed",
            "local_clip_deleted": not failed_paths,
            "local_clip_deleted_paths": deleted_paths,
            "local_clip_cleanup_errors": failed_paths,
            "local_clip_exists_after_cleanup": os.path.exists(clipped_video_path) if clipped_video_path else False,
        }
    return cleanup_by_asset


def collect_publish_metrics(
    *,
    publish_records: list[dict[str, Any]],
    publish_plans: list[dict[str, Any]] | None = None,
    drama_picks: list[dict[str, Any]] | None = None,
    video_assets: list[dict[str, Any]] | None = None,
    max_pages: int = 3,
    page_size: int = 100,
    wait_seconds: int = 90,
    poll_interval: int = 10,
    settle_timeout_seconds: int = 21600,
    cleanup_local_clips_after_publish: bool = True,
) -> dict[str, Any]:
    platforms = sorted(
        {
            str(record.get("platform") or "")
            for record in publish_records
            if str(record.get("platform") or "")
        }
    )
    remote_by_key = _fetch_remote_records(platforms=platforms, max_pages=max_pages, page_size=page_size)

    soft_deadline = time.time() + max(0, wait_seconds)
    hard_deadline = time.time() + max(max(0, wait_seconds), max(0, settle_timeout_seconds))
    while True:
        pending_keys = []
        for record in publish_records:
            key = (str(record.get("team_id") or ""), str(record.get("task_id") or ""))
            matched = remote_by_key.get(key)
            if matched and str(matched.get("status") or "").upper() in RUNNING_PUBLISH_STATUSES:
                pending_keys.append(key)
        if not pending_keys:
            break
        if time.time() >= hard_deadline:
            break
        time.sleep(max(1, poll_interval))
        remote_by_key = _fetch_remote_records(platforms=platforms, max_pages=max_pages, page_size=page_size)
        if time.time() >= soft_deadline:
            soft_deadline = time.time() + max(0, wait_seconds)

    plan_by_id = {str(item.get("id")): dict(item) for item in (publish_plans or [])}
    drama_by_serial = {str(item.get("serial_id") or ""): dict(item) for item in (drama_picks or [])}
    asset_by_id = {str(item.get("id")): dict(item) for item in (video_assets or [])}
    cleanup_by_asset = (
        _cleanup_local_publish_files(
            publish_records=publish_records,
            publish_plans=publish_plans,
            video_assets=video_assets,
            remote_by_key=remote_by_key,
        )
        if cleanup_local_clips_after_publish
        else {}
    )

    snapshots: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for record in publish_records:
        key = (str(record.get("team_id") or ""), str(record.get("task_id") or ""))
        matched = remote_by_key.get(key)
        if not matched:
            missing.append(
                {
                    "publish_record_id": record.get("id"),
                    "team_id": key[0],
                    "task_id": key[1],
                    "platform": record.get("platform"),
                }
            )
            continue
        plan = plan_by_id.get(str(record.get("publish_plan_id") or ""))
        drama = drama_by_serial.get(str((plan or {}).get("serial_id") or ""))
        asset = asset_by_id.get(str((plan or {}).get("video_asset_id") or ""))
        cleanup_info = cleanup_by_asset.get(str((plan or {}).get("video_asset_id") or ""), {})
        drama_info = {
            "serial_id": str((plan or {}).get("serial_id") or (drama or {}).get("serial_id") or ""),
            "task_id": str((drama or {}).get("task_id") or ""),
            "title": str((drama or {}).get("title") or ""),
            "app_id": str((drama or {}).get("app_id") or ""),
            "language": str((drama or {}).get("language") or ""),
            "episode_number": int((asset or {}).get("episode_number") or 0),
            "dedup_variant": str((asset or {}).get("dedup_variant") or ""),
            "clip_options": _parse_clip_options(asset),
            "clipped_video_path": str((asset or {}).get("clipped_video_path") or ""),
            "promotion_link": str((plan or {}).get("promotion_link") or ""),
            "promotion_code": str((plan or {}).get("promotion_code") or ""),
            **cleanup_info,
        }
        snapshots.append(
            {
                "publish_record_id": record.get("id"),
                "snapshot_day": 0,
                "views": int(matched.get("views") or 0),
                "likes": int(matched.get("likes") or 0),
                "comments": int(matched.get("comments") or 0),
                "shares": int(matched.get("shares") or 0),
                "revenue": float(matched.get("order_amount") or 0.0),
                "raw_payload": {
                    "drama": drama_info,
                    "publish_record": matched,
                },
            }
        )

    return {
        "snapshots": snapshots,
        "matched_count": len(snapshots),
        "missing": missing,
        "cleanup_count": len([item for item in cleanup_by_asset.values() if item.get("local_clip_deleted")]),
        "cleanup_failed_count": len([item for item in cleanup_by_asset.values() if item.get("local_clip_cleanup_status") == "delete_failed"]),
        "settled": not any(
            str(remote_by_key.get((str(record.get("team_id") or ""), str(record.get("task_id") or "")), {}).get("status") or "").upper()
            in RUNNING_PUBLISH_STATUSES
            for record in publish_records
        ),
    }
