#!/usr/bin/env python3
"""Push loop task results and runtime events back to the dashboard API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_API_BASE = os.getenv("AI_LOOP_DASHBOARD_API", "http://124.174.76.6")


def text(value: Any) -> str:
    return str(value or "").strip()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: str) -> Any:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def load_rows(path: str) -> list[dict[str, Any]]:
    data = read_json(path)
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        rows = data["rows"]
    elif isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = [data]
    else:
        raise SystemExit(f"unsupported JSON payload: {path}")
    if not all(isinstance(row, dict) for row in rows):
        raise SystemExit("tasks payload must contain objects")
    return rows


def post_rows(api_base: str, table: str, rows: list[dict[str, Any]], api_key: str = "") -> dict[str, Any]:
    body = json.dumps({"table": table, "rows": rows}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(f"{api_base.rstrip('/')}/api/ingest", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def load_strategy_context(path: str) -> dict[str, Any]:
    if not path:
        return {}
    data = read_json(path)
    if isinstance(data, dict) and isinstance(data.get("strategy_context"), dict):
        return data["strategy_context"]
    if isinstance(data, dict) and isinstance(data.get("selected_strategies"), dict):
        return {
            strategy_type: {
                "strategy_code": item.get("strategy_code"),
                "strategy_name": item.get("strategy_name"),
            }
            for strategy_type, item in data["selected_strategies"].items()
            if isinstance(item, dict)
        }
    return data if isinstance(data, dict) else {}


def merge_clip_params(existing: Any, strategy_context: dict[str, Any], extra: dict[str, Any]) -> str:
    if isinstance(existing, dict):
        params = dict(existing)
    else:
        raw = text(existing)
        if raw:
            try:
                params = json.loads(raw)
                if not isinstance(params, dict):
                    params = {"raw": raw}
            except json.JSONDecodeError:
                params = {"raw": raw}
        else:
            params = {}
    if strategy_context:
        params["strategy_context"] = strategy_context
    params.update({k: v for k, v in extra.items() if v not in ("", None)})
    return json.dumps(params, ensure_ascii=False, separators=(",", ":"))


def is_invalid_publish_status(row: dict[str, Any]) -> bool:
    return text(row.get("publish_status")).lower() in {"failed", "cancelled", "canceled", "error"}


def reason_text(row: dict[str, Any]) -> str:
    return " ".join(
        text(row.get(field))
        for field in ("publish_fail_reason", "clip_fail_reason", "fail_stage")
        if text(row.get(field))
    ).lower()


def is_clip_queued(row: dict[str, Any]) -> bool:
    reason = reason_text(row)
    params = text(row.get("clip_params")).lower()
    return "last_status=queued" in reason or "last_status=queued" in params or "queued" in text(row.get("clip_last_status")).lower()


def is_clip_done(row: dict[str, Any]) -> bool:
    return any(text(row.get(field)) for field in ("clip_end_time", "output_duration_sec", "output_size_mb", "social_post_id")) or text(row.get("publish_status")).lower() in {"success", "reviewing"}


def is_clipping(row: dict[str, Any]) -> bool:
    if is_clip_done(row) or is_clip_queued(row) or is_invalid_publish_status(row):
        return False
    return bool(text(row.get("clip_start_time")) or "last_status=processing" in reason_text(row) or "last_status=running" in reason_text(row))


def account_key(row: dict[str, Any]) -> str:
    for field in ("social_account_id", "douyin_t8_account", "channel_id", "uid", "task_id"):
        value = text(row.get(field))
        if value:
            return value
    return ""


def build_node_metrics(args: argparse.Namespace, task_rows: list[dict[str, Any]]) -> dict[str, Any]:
    selected_dramas = {text(row.get("drama_name")) for row in task_rows if text(row.get("drama_name"))}
    accounts = {account_key(row) for row in task_rows if account_key(row)}
    status_distribution = Counter(text(row.get("publish_status")).lower() or "unknown" for row in task_rows)
    success = status_distribution.get("success", 0)
    failed = status_distribution.get("failed", 0)
    scheduled = sum(1 for row in task_rows if text(row.get("short_link_publish_time")) and not is_invalid_publish_status(row))
    daily_target = args.daily_target if args.daily_target is not None else len(task_rows)
    rounds = {text(row.get("round_name")) for row in task_rows if text(row.get("round_name"))}
    return {
        "task_count": len(task_rows),
        "success_count": success,
        "failed_count": failed,
        "pending_count": status_distribution.get("pending", 0),
        "reviewing_count": status_distribution.get("reviewing", 0),
        "cancelled_count": status_distribution.get("cancelled", 0) + status_distribution.get("canceled", 0),
        "publish_status_distribution": dict(status_distribution.most_common()),
        "round_count": len(rounds),
        "account_count": len(accounts),
        "drama_count": len(selected_dramas),
        "round_selected_drama_count": len(selected_dramas),
        "round_target_account_count": len(accounts),
        "clip_tools": sorted({text(row.get("clip_tool")) for row in task_rows if text(row.get("clip_tool"))}),
        "clip_done_count": sum(1 for row in task_rows if is_clip_done(row)),
        "clip_queued_count": sum(1 for row in task_rows if is_clip_queued(row)),
        "clipping_count": sum(1 for row in task_rows if is_clipping(row)),
        "publish_scheduled_count": scheduled,
        "daily_publish_target": daily_target,
        "unpublished_target_gap_count": max(daily_target - success, 0),
        "publish_start_time": args.publish_start_time,
        "publish_account_interval_seconds": args.publish_interval_seconds,
    }


def normalize_task(row: dict[str, Any], args: argparse.Namespace, strategy_context: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.setdefault("date", args.date or datetime.now().strftime("%Y-%m-%d"))
    out.setdefault("assignee", args.owner)
    out.setdefault("assignee_source", "skill_owner")
    if args.uid:
        out.setdefault("uid", args.uid)
    out.setdefault("publish_status", "pending")
    out.setdefault("update_time", now_text())
    if args.round_name and not text(out.get("round_name")):
        out["round_name"] = args.round_name
    if args.ab_group and not text(out.get("ab_group")):
        out["ab_group"] = args.ab_group
    out.setdefault("loop_name", args.loop_name)
    out.setdefault("strategy_binding_status", "loop_bound" if strategy_context else "telemetry_only")
    extra_params = {
        "loop_name": args.loop_name,
        "strategy_run_id": args.strategy_run_id,
        "round_name": args.round_name,
        "ab_group": args.ab_group,
    }
    out["clip_params"] = merge_clip_params(out.get("clip_params"), strategy_context, extra_params)
    if not text(out.get("task_id")):
        stable_parts = {
            "loop_name": args.loop_name,
            "round_name": text(out.get("round_name")),
            "date": text(out.get("date")),
            "account": text(out.get("social_account_id") or out.get("douyin_t8_account") or out.get("channel_id")),
            "drama_name": text(out.get("drama_name")),
            "social_post_id": text(out.get("social_post_id")),
        }
        seed = json.dumps(stable_parts, ensure_ascii=False, sort_keys=True)
        out["task_id"] = f"loop_result:{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]}"
    return out


def build_event(args: argparse.Namespace, task_rows: list[dict[str, Any]], strategy_context: dict[str, Any]) -> dict[str, Any]:
    event_time = now_text()
    node_metrics = build_node_metrics(args, task_rows)
    success = node_metrics["success_count"]
    failed = node_metrics["failed_count"]
    selected = next(iter(strategy_context.values()), {}) if strategy_context else {}
    event_id = args.event_id or f"skill-result:{args.loop_name}:{args.owner}:{args.round_name or 'round'}:{event_time.replace(' ', 'T')}"
    return {
        "event_id": event_id[:255],
        "event_time": event_time,
        "owner": args.owner,
        "loop_name": args.loop_name,
        "event_type": args.event_type,
        "event_title": args.event_title or f"{args.loop_name} 回写执行结果",
        "event_detail": args.event_detail or f"回写 {len(task_rows)} 条任务，成功 {success}，失败 {failed}。",
        "strategy_type": text(selected.get("strategy_type")),
        "strategy_code": text(selected.get("strategy_code")),
        "strategy_name": text(selected.get("strategy_name")),
        "round_name": args.round_name,
        "ab_group": args.ab_group,
        "severity": "warn" if failed else "info",
        "metric_json": json.dumps(node_metrics, ensure_ascii=False),
        "source": "video_pipeline_tracker_skill",
        "source_file": args.tasks,
        "created_at": event_time,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Push loop task results/runtime event into dashboard API")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--api-key", default=os.getenv("INGEST_API_KEY", ""))
    parser.add_argument("--tasks", required=True, help="JSON list, object, or {'rows': [...]} of video_pipeline_tasks")
    parser.add_argument("--strategy-context", default="", help="Output from claim_strategy_binding.py or pull bundle")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--uid", default="")
    parser.add_argument("--loop-name", required=True)
    parser.add_argument("--round-name", default="")
    parser.add_argument("--ab-group", default="")
    parser.add_argument("--strategy-run-id", default="")
    parser.add_argument("--date", default="")
    parser.add_argument("--daily-target", type=int, default=None, help="Daily publish target for unpublished gap metrics")
    parser.add_argument("--publish-start-time", default="", help="Planned publish start time, e.g. 2026-06-22 19:00:00")
    parser.add_argument("--publish-interval-seconds", type=int, default=None, help="Planned interval between account publishes")
    parser.add_argument("--event-type", default="loop_result")
    parser.add_argument("--event-id", default="")
    parser.add_argument("--event-title", default="")
    parser.add_argument("--event-detail", default="")
    parser.add_argument("--skip-event", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("-o", "--output", default="", help="Write normalized task rows")
    args = parser.parse_args()

    strategy_context = load_strategy_context(args.strategy_context)
    tasks = [normalize_task(row, args, strategy_context) for row in load_rows(args.tasks)]
    event_rows = [] if args.skip_event else [build_event(args, tasks, strategy_context)]

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps({"rows": tasks, "runtime_events": event_rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    result: dict[str, Any] = {
        "ok": True,
        "execute": args.execute,
        "task_rows": len(tasks),
        "event_rows": len(event_rows),
        "sample_task": tasks[:1],
        "sample_event": event_rows[:1],
    }
    if args.execute:
        result["task_response"] = post_rows(args.api_base, "video_pipeline_tasks", tasks, api_key=args.api_key)
        if event_rows:
            result["event_response"] = post_rows(args.api_base, "ai_loop_runtime_events", event_rows, api_key=args.api_key)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
