#!/usr/bin/env python3
"""
Convert Steven-jiao loop telemetry task traces to video_pipeline_tasks rows.

The Steven project is treated as a fixed-owner loop:
  assignee = 焦千为
  assignee_source = project_owner
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OWNER = "焦千为"
DEFAULT_UID = "2265845568"
DEFAULT_LOOP_NAME = "steven-jiao-ai-loop"


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_team_map(loop_root: Path) -> dict[str, dict[str, Any]]:
    generated = loop_root / "config" / "generated" / "dashboard-steven-team-languages.json"
    path = generated if generated.exists() else loop_root / "config" / "fb-shortdrama-team-languages.json"
    if not path.exists():
        return {}
    data = read_json(path)
    raw = data.get("team_languages") if isinstance(data, dict) else {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def node_fields(trace: dict[str, Any], node_name: str) -> dict[str, Any]:
    for node in trace.get("nodes") or []:
        if isinstance(node, dict) and node.get("node") == node_name:
            fields = node.get("fields")
            return fields if isinstance(fields, dict) else {}
    return {}


def first_failed_node(trace: dict[str, Any]) -> str:
    for node in trace.get("nodes") or []:
        if isinstance(node, dict) and node.get("status") == "failed":
            return str(node.get("node") or "")
    return ""


def infer_uid(trace: dict[str, Any], default_uid: str) -> str:
    upload = node_fields(trace, "upload")
    for key in ("file_url", "uploaded_url", "oss_url"):
        value = str(upload.get(key) or "")
        match = re.search(r"/ai%2F(\d{6,})%2F|/ai/(\d{6,})/", value)
        if match:
            return match.group(1) or match.group(2)
    return default_uid


def map_status(status: str) -> str:
    status = (status or "").strip().lower()
    if status in {"published_submitted", "reviewing", "processing"}:
        return "reviewing"
    if status in {"success", "done", "published", "publish_success"}:
        return "success"
    if status in {"failed", "error"}:
        return "failed"
    if status in {"cancelled", "canceled"}:
        return "cancelled"
    return "pending"


def map_fail_stage(trace: dict[str, Any]) -> str | None:
    failed = first_failed_node(trace)
    if not failed and not trace.get("failure_reason"):
        return None
    if failed in {"candidate_selection", "material_acquire", "video_probe"}:
        return "clip"
    if failed in {"upload"}:
        return "upload"
    if failed in {"publish_submit", "publish_status_confirm"}:
        return "publish"
    if failed in {"clip_task_submit", "clip_task_poll", "output_generation"}:
        return "clip"
    return "publish" if trace.get("failure_reason") else None


def mb(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return round(float(value) / 1024 / 1024, 3)
    except (TypeError, ValueError):
        return None


def trace_to_row(
    trace: dict[str, Any],
    *,
    team_map: dict[str, dict[str, Any]],
    owner: str,
    default_uid: str,
    loop_name: str,
    daily_target: int | None,
    publish_start_time: str,
    publish_interval_seconds: int | None,
) -> dict[str, Any]:
    team_id = str(trace.get("team_id") or "")
    team = team_map.get(team_id) or {}
    clip = trace.get("clip_quality") if isinstance(trace.get("clip_quality"), dict) else {}
    candidate = node_fields(trace, "candidate_selection")
    upload = node_fields(trace, "upload")
    publish_submit = node_fields(trace, "publish_submit")
    cleanup = node_fields(trace, "cleanup_archive")

    width = clip.get("output_width")
    height = clip.get("output_height")
    quality = f"{width}x{height}" if width and height else None
    publish_status = map_status(str(trace.get("status") or ""))
    failure_reason = str(trace.get("failure_reason") or "") or None

    clip_params = {
        "business": "shortdrama",
        "source_kind": "steven_jiao_telemetry",
        "source": trace.get("source_type") or candidate.get("source"),
        "loop_name": loop_name,
        "app_id": trace.get("app_id") or candidate.get("app_id"),
        "serial_id": trace.get("serial_id") or candidate.get("serial_id"),
        "ab_group": trace.get("ab_group"),
        "round": trace.get("round"),
        "scheduled_at": trace.get("scheduled_at"),
        "daily_publish_target": daily_target,
        "publish_start_time": publish_start_time,
        "publish_account_interval_seconds": publish_interval_seconds,
        "clip_engine": clip.get("clip_engine"),
        "cut_type": clip.get("cut_type"),
        "strategy_binding_status": "telemetry_only",
        "candidate_task_id": candidate.get("task_id"),
        "episode_order": candidate.get("episode_order"),
        "selected_reason": candidate.get("selected_reason"),
        "score": candidate.get("score"),
    }

    return {
        "date": trace.get("date"),
        "short_link_publish_time": trace.get("scheduled_at"),
        "assignee": owner,
        "assignee_source": "project_owner",
        "uid": infer_uid(trace, default_uid),
        "task_id": f"steven_jiao:{trace.get('trace_id')}",
        "trace_id": trace.get("trace_id"),
        "douyin_t8_account": team.get("social_name") or node_fields(trace, "preflight").get("account_name") or "Facebook 账号",
        "channel_id": team_id,
        "social_account_id": str(team.get("social_account_id") or team.get("account_id") or ""),
        "account_type": "personal",
        "clip_tool": clip.get("clip_engine") or "auto",
        "drama_name": trace.get("drama_title"),
        "drama_timestamp": trace.get("scheduled_at"),
        "material_source": trace.get("source_type") or "h5_new",
        "clip_duration_sec": clip.get("clip_elapsed_seconds"),
        "clip_params": json.dumps(clip_params, ensure_ascii=False, separators=(",", ":")),
        "output_duration_sec": clip.get("output_duration_seconds") or clip.get("output_file_duration_seconds"),
        "output_size_mb": mb(clip.get("output_file_size") or upload.get("file_size")),
        "output_quality": quality,
        "upload_retry_count": upload.get("retry_count") or 0,
        "publish_req_start_time": publish_submit.get("request_start_time"),
        "publish_req_end_time": publish_submit.get("request_end_time"),
        "publish_duration_sec": publish_submit.get("elapsed_seconds"),
        "social_post_id": publish_submit.get("post_id") or trace.get("publish_task_id"),
        "publish_status": publish_status,
        "fail_stage": map_fail_stage(trace),
        "publish_fail_reason": failure_reason,
        "retry_count": publish_submit.get("retry_count") or 0,
        "update_time": cleanup.get("finished_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "clip_fail_reason": failure_reason if map_fail_stage(trace) == "clip" else None,
        "social_name": team.get("social_name"),
        "enriched_team_id": team_id,
        "_team_id": team_id,
        "round_name": trace.get("round"),
        "ab_group": trace.get("ab_group"),
        "loop_name": loop_name,
        "source_type": trace.get("source_type"),
        "strategy_binding_status": "telemetry_only",
    }


def existing_task_ids(api_base: str) -> set[str]:
    url = f"{api_base.rstrip('/')}/api/table/video_pipeline_tasks?limit=100000"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            payload = json.load(resp)
        return {str(row.get("task_id")) for row in payload.get("rows", []) if row.get("task_id")}
    except Exception as exc:
        print(f"WARNING: failed to load existing task ids: {exc}", file=sys.stderr)
        return set()


def post_rows(api_base: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    body = json.dumps({"table": "video_pipeline_tasks", "rows": rows}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/api/ingest",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Steven-jiao telemetry into video_pipeline_tasks")
    parser.add_argument("--loop-root", default="/opt/steven-jiao-ai-loop")
    parser.add_argument("--date", action="append", help="Telemetry date YYYY-MM-DD. Can repeat. Default: all dates")
    parser.add_argument("--api-base", default="http://127.0.0.1:8770")
    parser.add_argument("--assignee", default=DEFAULT_OWNER)
    parser.add_argument("--uid", default=DEFAULT_UID)
    parser.add_argument("--loop-name", default=DEFAULT_LOOP_NAME)
    parser.add_argument("--daily-target", type=int, default=None, help="Daily publish target stored in clip_params for unpublished gap metrics")
    parser.add_argument("--publish-start-time", default="", help="Planned publish start time stored in clip_params")
    parser.add_argument("--publish-interval-seconds", type=int, default=None, help="Planned interval between account publishes stored in clip_params")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--skip-existing", action="store_true", help="Skip rows whose task_id already exists. Default posts all parsed rows so later status changes can be upserted by the API.")
    parser.add_argument("--batch-size", type=int, default=300)
    parser.add_argument("-o", "--output", default="")
    args = parser.parse_args()

    loop_root = Path(args.loop_root)
    telemetry_root = loop_root / "runtime" / "telemetry"
    dates = args.date or sorted(p.name for p in telemetry_root.iterdir() if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", p.name))
    team_map = load_team_map(loop_root)

    rows: list[dict[str, Any]] = []
    trace_files = 0
    for day in dates:
        day_dir = telemetry_root / day
        for path in sorted(day_dir.glob("round*.task_trace.jsonl")):
            trace_files += 1
            if path.stat().st_size == 0:
                continue
            for trace in iter_jsonl(path):
                rows.append(trace_to_row(
                    trace,
                    team_map=team_map,
                    owner=args.assignee,
                    default_uid=args.uid,
                    loop_name=args.loop_name,
                    daily_target=args.daily_target,
                    publish_start_time=args.publish_start_time,
                    publish_interval_seconds=args.publish_interval_seconds,
                ))

    existing = existing_task_ids(args.api_base) if args.execute and args.skip_existing else set()
    post_rows_payload = [row for row in rows if row.get("task_id") not in existing] if args.skip_existing else rows

    summary = {
        "dates": dates,
        "trace_files": trace_files,
        "parsed_rows": len(rows),
        "rows_to_post": len(post_rows_payload),
        "skipped_existing": len(rows) - len(post_rows_payload),
        "skip_existing": args.skip_existing,
        "assignee": args.assignee,
        "loop_name": args.loop_name,
        "execute": args.execute,
    }

    if args.output:
        Path(args.output).write_text(json.dumps(post_rows_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.execute:
        print(json.dumps({**summary, "sample": post_rows_payload[:2]}, ensure_ascii=False, indent=2))
        return 0

    responses = []
    for i in range(0, len(post_rows_payload), args.batch_size):
        batch = post_rows_payload[i:i + args.batch_size]
        if not batch:
            continue
        responses.append(post_rows(args.api_base, batch))
    print(json.dumps({**summary, "responses": responses}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
