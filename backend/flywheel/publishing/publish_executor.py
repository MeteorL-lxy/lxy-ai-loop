from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from inbeidou_cli import create_publish_post, require_success, upload_publish_file

from ..clipping.video_normalizer import ensure_vertical_publish_ready
from .constraints import (
    validate_publish_clip_constraints,
    validate_promotion_constraints,
    validate_source_episode_constraints,
)


def _ensure_vertical_publish_file(local_clip_path: str, *, target_width: int, target_height: int) -> str:
    normalized = ensure_vertical_publish_ready(
        input_path=local_clip_path,
        output_path=Path(local_clip_path).with_name(
            f"{Path(local_clip_path).stem}_{target_width}x{target_height}_publish.mp4"
        ),
        target_width=target_width,
        target_height=target_height,
    )
    return str(normalized["path"])


def _build_publish_payload(plan: dict[str, Any], file_url: str) -> dict[str, Any]:
    scheduled_at = str(plan.get("scheduled_at") or "").strip()
    payload = {
        "team_id": str(plan.get("team_id") or ""),
        "text": str(plan.get("caption") or ""),
        "file_url": file_url,
        "post_status": 1 if scheduled_at else 0,
        "social_type": str(plan.get("platform") or ""),
    }
    if scheduled_at:
        payload["post_date"] = scheduled_at
    if payload["social_type"] in {"FACEBOOK", "INSTAGRAM"}:
        payload["type"] = "REEL"
    return payload


def execute_publish_plans(
    *,
    publish_plans: list[dict[str, Any]],
    video_assets: list[dict[str, Any]],
    target_width: int,
    target_height: int,
    execute_limit: int,
    execute_concurrency: int,
) -> dict[str, Any]:
    asset_by_id = {str(asset.get("id")): dict(asset) for asset in video_assets if asset.get("id") is not None}

    preview: list[dict[str, Any]] = []
    eligible_plans: list[dict[str, Any]] = []
    executed = 0
    for plan in publish_plans:
        asset = asset_by_id.get(str(plan.get("video_asset_id") or ""))
        local_clip_path = str((asset or {}).get("clipped_video_path") or "")
        if not asset or not local_clip_path or not Path(local_clip_path).exists():
            preview.append(
                {
                    "publish_plan_id": plan.get("id"),
                    "platform": plan.get("platform"),
                    "team_id": plan.get("team_id"),
                    "status": "skipped_missing_asset",
                }
            )
            continue
        if execute_limit > 0 and executed >= execute_limit:
            preview.append(
                {
                    "publish_plan_id": plan.get("id"),
                    "platform": plan.get("platform"),
                    "team_id": plan.get("team_id"),
                    "status": "skipped_execute_limit",
                }
            )
            continue
        eligible_plans.append(dict(plan))
        executed += 1

    executed_results = _run_parallel_ordered(
        eligible_plans,
        execute_concurrency,
        lambda plan: _execute_publish_plan(
            plan,
            asset_by_id=asset_by_id,
            target_width=target_width,
            target_height=target_height,
        ),
    )
    records: list[dict[str, Any]] = []
    for item in executed_results:
        records.extend(item.get("records") or [])
        if item.get("preview"):
            preview.append(item["preview"])
            continue
        preview.append(
            {
                "publish_plan_id": item.get("id"),
                "platform": item.get("platform"),
                "team_id": item.get("team_id"),
                "status": "failed",
                "error": str(item.get("error") or ""),
            }
        )

    return {
        "records": records,
        "preview": preview,
        "executed_count": len(eligible_plans),
    }


def _run_parallel_ordered(
    items: list[dict[str, Any]],
    max_workers: int,
    worker,
) -> list[dict[str, Any]]:
    if max_workers <= 1:
        return [worker(item) for item in items]

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(worker, item): item for item in items}
        for future in as_completed(future_map):
            original = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({**original, "status": "failed", "error": str(exc)})
    results.sort(key=lambda item: int(item.get("id") or 0))
    return results


def _execute_publish_plan(
    plan: dict[str, Any],
    *,
    asset_by_id: dict[str, dict[str, Any]],
    target_width: int,
    target_height: int,
) -> dict[str, Any]:
    asset = asset_by_id.get(str(plan.get("video_asset_id") or ""))
    local_clip_path = str((asset or {}).get("clipped_video_path") or "")
    episode_selection = (
        ((asset or {}).get("clip_options") or {}).get("episode_selection")
        if isinstance((asset or {}).get("clip_options"), dict)
        else {}
    )
    validate_source_episode_constraints(episode_selection if isinstance(episode_selection, dict) else {})
    publish_ready_path = _ensure_vertical_publish_file(
        local_clip_path,
        target_width=target_width,
        target_height=target_height,
    )
    clip_meta = validate_publish_clip_constraints(
        {
            "downloaded_file": local_clip_path,
            "publish_ready_file": publish_ready_path,
        }
    )
    validate_promotion_constraints(
        str(plan.get("platform") or ""),
        {
            "promotion_link": str(plan.get("promotion_link") or ""),
            "caption": str(plan.get("caption") or ""),
        },
    )
    upload_context = upload_publish_file(publish_ready_path)
    payload = _build_publish_payload(plan, str(upload_context.get("publish_file_url") or ""))
    body = require_success(create_publish_post(payload), "发布帖子")
    tasks = body.get("tasks") if isinstance(body.get("tasks"), list) else []
    if not tasks:
        tasks = [
            {
                "team_id": plan.get("team_id"),
                "task_id": body.get("task_id"),
                "post_id": body.get("post_id"),
                "status": body.get("status") or "SUBMITTED",
            }
        ]

    records: list[dict[str, Any]] = []
    for task in tasks:
        records.append(
            {
                "publish_plan_id": plan.get("id"),
                "team_id": str(task.get("team_id") or plan.get("team_id") or ""),
                "task_id": str(task.get("task_id") or ""),
                "platform": str(plan.get("platform") or ""),
                "platform_post_id": str(task.get("post_id") or ""),
                "post_url": str(task.get("post_url") or task.get("url") or ""),
                "published_at": str(plan.get("scheduled_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                "status": str(task.get("status") or body.get("status") or "SUBMITTED"),
                "raw_payload": {
                    "payload": payload,
                    "publish_ready_path": publish_ready_path,
                    "publish_clip_meta": clip_meta,
                    "upload": upload_context,
                    "response": body,
                    "task": task,
                },
            }
        )
    return {
        "id": plan.get("id"),
        "records": records,
        "preview": {
            "publish_plan_id": plan.get("id"),
            "platform": plan.get("platform"),
            "team_id": plan.get("team_id"),
            "task_count": len(tasks),
            "status": "submitted",
        },
    }
