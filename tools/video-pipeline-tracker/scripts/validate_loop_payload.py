#!/usr/bin/env python3
"""Validate a loop task payload before pushing it to the dashboard."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = ("task_id", "date", "drama_name", "publish_status")
RECOMMENDED_FIELDS = ("round_name", "clip_tool", "assignee")
ALLOWED_STATUS = {"success", "failed", "pending", "reviewing", "cancelled", "canceled", "error"}


def text(value: Any) -> str:
    return str(value or "").strip()


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def parse_jsonish(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    raw = text(value)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_rows(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        rows = data["rows"]
    elif isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = [data]
    else:
        raise SystemExit("payload must be a JSON object, list, or {'rows': [...]}")
    if not all(isinstance(row, dict) for row in rows):
        raise SystemExit("all rows must be JSON objects")
    return rows


def row_loop_name(row: dict[str, Any]) -> str:
    return text(row.get("loop_name")) or text(parse_jsonish(row.get("clip_params")).get("loop_name"))


def row_metric_value(row: dict[str, Any], key: str) -> Any:
    if has_value(row.get(key)):
        return row.get(key)
    params = parse_jsonish(row.get("clip_params"))
    if has_value(params.get(key)):
        return params.get(key)
    return None


def account_key(row: dict[str, Any]) -> str:
    for field in ("channel_id", "social_account_id", "douyin_t8_account", "uid", "task_id"):
        value = text(row.get(field))
        if value:
            return value
    return ""


def parse_dt(value: Any) -> datetime | None:
    raw = text(value)
    if not raw:
        return None
    raw = raw.replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def to_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return int(parsed)


def reason_text(row: dict[str, Any]) -> str:
    parts = [text(row.get(field)) for field in ("publish_fail_reason", "clip_fail_reason", "fail_stage", "clip_params")]
    return " ".join(part for part in parts if part).lower()


def is_invalid_publish_status(row: dict[str, Any]) -> bool:
    return text(row.get("publish_status")).lower() in {"failed", "cancelled", "canceled", "error"}


def is_clip_queued(row: dict[str, Any]) -> bool:
    reason = reason_text(row)
    return text(row.get("clip_status")).lower() == "queued" or text(row.get("clip_last_status")).lower() == "queued" or "last_status=queued" in reason


def is_clip_done(row: dict[str, Any]) -> bool:
    if text(row.get("clip_status")).lower() in {"completed", "done"}:
        return True
    if any(has_value(row.get(field)) for field in ("clip_end_time", "output_duration_sec", "output_size_mb", "social_post_id")):
        return True
    return text(row.get("publish_status")).lower() in {"success", "reviewing"}


def is_clipping(row: dict[str, Any]) -> bool:
    if is_clip_done(row) or is_clip_queued(row) or is_invalid_publish_status(row):
        return False
    if text(row.get("clip_status")).lower() in {"clipping", "processing", "running"}:
        return True
    reason = reason_text(row)
    return has_value(row.get("clip_start_time")) or "last_status=processing" in reason or "last_status=running" in reason


def is_scheduled_publish(row: dict[str, Any]) -> bool:
    return has_value(row.get("short_link_publish_time")) and not is_invalid_publish_status(row)


def validate(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    task_ids = [text(row.get("task_id")) for row in rows if text(row.get("task_id"))]
    duplicates = [task_id for task_id, count in Counter(task_ids).items() if count > 1]
    if duplicates:
        errors.append(f"duplicate task_id: {', '.join(duplicates[:10])}")

    for index, row in enumerate(rows, start=1):
        for field in REQUIRED_FIELDS:
            if not has_value(row.get(field)):
                errors.append(f"row {index}: missing required field {field}")
        status = text(row.get("publish_status")).lower()
        if status and status not in ALLOWED_STATUS:
            errors.append(f"row {index}: unsupported publish_status {status}")
        if not (row_loop_name(row) or args.loop_name):
            errors.append(f"row {index}: missing loop_name; pass --loop-name or write row.loop_name")
        if not account_key(row):
            errors.append(f"row {index}: missing account key; need social_account_id/douyin_t8_account/channel_id/uid")
        for field in RECOMMENDED_FIELDS:
            if not has_value(row.get(field)):
                warnings.append(f"row {index}: recommended field {field} is empty")
        if not (is_clip_done(row) or is_clip_queued(row) or is_clipping(row) or is_invalid_publish_status(row)):
            warnings.append(f"row {index}: no clear clip status evidence")

    target_candidates = [
        to_int(row_metric_value(row, key))
        for row in rows
        for key in ("daily_publish_target", "round_account_count", "target_account_count")
    ]
    target_candidates = [value for value in target_candidates if value is not None]
    daily_target = args.daily_target if args.daily_target is not None else (max(target_candidates) if target_candidates else len(rows))
    published = sum(1 for row in rows if text(row.get("publish_status")).lower() == "success")
    scheduled_times = [dt for dt in (parse_dt(row.get("short_link_publish_time")) for row in rows if is_scheduled_publish(row)) if dt]
    publish_start_candidates = [
        parse_dt(row_metric_value(row, key))
        for row in rows
        for key in ("publish_schedule_start_time", "publish_start_time")
    ]
    publish_start_candidates = [value for value in publish_start_candidates if value]
    publish_start = args.publish_start_time or (
        min(publish_start_candidates).strftime("%Y-%m-%d %H:%M:%S") if publish_start_candidates
        else (min(scheduled_times).strftime("%Y-%m-%d %H:%M:%S") if scheduled_times else "")
    )
    interval_candidates = [
        to_int(row_metric_value(row, key))
        for row in rows
        for key in ("publish_interval_sec", "publish_account_interval_seconds")
    ]
    interval_candidates = [value for value in interval_candidates if value is not None]
    publish_interval = args.publish_interval_seconds if args.publish_interval_seconds is not None else (interval_candidates[0] if interval_candidates else None)
    if not publish_start:
        warnings.append("publish_start_time is not available; pass --publish-start-time or write publish_start_time/publish_schedule_start_time")
    if publish_interval is None:
        warnings.append("publish interval is not available; pass --publish-interval-seconds or write publish_interval_sec")
    if args.daily_target is None and not target_candidates:
        warnings.append("daily_publish_target is not available; unpublished gap falls back to matched row count")

    metrics = {
        "row_count": len(rows),
        "loop_names": sorted({row_loop_name(row) or args.loop_name for row in rows if row_loop_name(row) or args.loop_name}),
        "round_count": len({text(row.get("round_name")) for row in rows if text(row.get("round_name"))}),
        "selected_drama_count": len({text(row.get("drama_name")) for row in rows if text(row.get("drama_name"))}),
        "account_count": len({account_key(row) for row in rows if account_key(row)}),
        "clip_tools": sorted({text(row.get("clip_tool")) for row in rows if text(row.get("clip_tool"))}),
        "clip_done_count": sum(1 for row in rows if is_clip_done(row)),
        "clip_queued_count": sum(1 for row in rows if is_clip_queued(row)),
        "clipping_count": sum(1 for row in rows if is_clipping(row)),
        "published_count": published,
        "prepublish_count": sum(1 for row in rows if is_scheduled_publish(row)),
        "daily_publish_target": daily_target,
        "unpublished_target_gap_count": max(daily_target - published, 0),
        "publish_start_time": publish_start,
        "publish_interval_seconds": publish_interval,
        "publish_status_distribution": dict(Counter(text(row.get("publish_status")).lower() or "unknown" for row in rows).most_common()),
    }
    return {
        "ok": not errors and (not args.strict or not warnings),
        "strict": args.strict,
        "errors": errors,
        "warnings": warnings[:50],
        "warning_count": len(warnings),
        "metrics": metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a loop task payload before dashboard ingest")
    parser.add_argument("--tasks", required=True, help="JSON object/list or {'rows': [...]}")
    parser.add_argument("--loop-name", default="", help="Expected loop name if rows do not contain loop_name yet")
    parser.add_argument("--daily-target", type=int, default=None)
    parser.add_argument("--publish-start-time", default="")
    parser.add_argument("--publish-interval-seconds", type=int, default=None)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as validation failures")
    args = parser.parse_args()

    result = validate(load_rows(args.tasks), args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["errors"]:
        return 1
    if args.strict and result["warnings"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
