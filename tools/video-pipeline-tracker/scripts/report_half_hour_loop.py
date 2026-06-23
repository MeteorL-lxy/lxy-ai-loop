#!/usr/bin/env python3
"""Run a half-hour loop report: validate tasks, then push a snapshot event."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from validate_loop_payload import load_rows, parse_dt, validate  # noqa: E402


def text(value: Any) -> str:
    return str(value or "").strip()


def default_window(mode: str) -> tuple[datetime, datetime]:
    now = datetime.now().replace(second=0, microsecond=0)
    current_start = now.replace(minute=0 if now.minute < 30 else 30)
    if mode == "current":
        return current_start, current_start + timedelta(minutes=30)
    return current_start - timedelta(minutes=30), current_start


def parse_window(value: str) -> datetime:
    parsed = parse_dt(value)
    if not parsed:
        raise SystemExit(f"invalid datetime: {value}")
    return parsed


def row_time(row: dict[str, Any]) -> datetime | None:
    for field in ("update_time", "drama_timestamp", "short_link_publish_time", "publish_req_start_time", "date"):
        parsed = parse_dt(row.get(field))
        if parsed:
            return parsed
    return None


def filter_window(rows: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    filtered = []
    for row in rows:
        parsed = row_time(row)
        if parsed and start <= parsed < end:
            filtered.append(row)
    return filtered


def write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


def run_push(args: argparse.Namespace, tasks_path: Path, window_start: datetime, window_end: datetime) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "push_loop_result.py"),
        "--api-base", args.api_base,
        "--tasks", str(tasks_path),
        "--owner", args.owner,
        "--loop-name", args.loop_name,
        "--event-type", "loop_window_report",
        "--event-title", f"{args.loop_name} 半小时窗口上报",
        "--event-detail", f"窗口 {window_start:%Y-%m-%d %H:%M:%S} 至 {window_end:%Y-%m-%d %H:%M:%S} 上报 {tasks_path.name}",
    ]
    optional_pairs = [
        ("--uid", args.uid),
        ("--round-name", args.round_name),
        ("--ab-group", args.ab_group),
        ("--strategy-context", args.strategy_context),
        ("--daily-target", args.daily_target),
        ("--publish-start-time", args.publish_start_time),
        ("--publish-interval-seconds", args.publish_interval_seconds),
        ("--api-key", args.api_key),
    ]
    for flag, value in optional_pairs:
        if value not in ("", None):
            cmd.extend([flag, str(value)])
    if args.execute:
        cmd.append("--execute")
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"push_loop_result.py failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"push_loop_result.py returned non-JSON output: {exc}\n{proc.stdout}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and report loop data every half hour")
    parser.add_argument("--tasks", required=True, help="Loop task JSON object/list or {'rows': [...]}")
    parser.add_argument("--api-base", default="http://124.174.76.6")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--uid", default="")
    parser.add_argument("--loop-name", required=True)
    parser.add_argument("--round-name", default="")
    parser.add_argument("--ab-group", default="")
    parser.add_argument("--strategy-context", default="")
    parser.add_argument("--daily-target", type=int, default=None)
    parser.add_argument("--publish-start-time", default="")
    parser.add_argument("--publish-interval-seconds", type=int, default=None)
    parser.add_argument("--window-mode", choices=["previous", "current"], default="previous")
    parser.add_argument("--window-start", default="", help="Override report window start")
    parser.add_argument("--window-end", default="", help="Override report window end")
    parser.add_argument("--filter-window", action="store_true", help="Only report rows whose time is inside the half-hour window")
    parser.add_argument("--strict", action="store_true", help="Treat validation warnings as failures")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", default="", help="Write selected rows and report JSON here")
    args = parser.parse_args()

    window_start, window_end = default_window(args.window_mode)
    if args.window_start:
        window_start = parse_window(args.window_start)
    if args.window_end:
        window_end = parse_window(args.window_end)
    if window_end <= window_start:
        raise SystemExit("window-end must be after window-start")

    rows = load_rows(args.tasks)
    selected_rows = filter_window(rows, window_start, window_end) if args.filter_window else rows

    validation_args = argparse.Namespace(
        loop_name=args.loop_name,
        daily_target=args.daily_target,
        publish_start_time=args.publish_start_time,
        publish_interval_seconds=args.publish_interval_seconds,
        strict=args.strict,
    )
    validation = validate(selected_rows, validation_args)
    if validation["errors"] or (args.strict and validation["warnings"]):
        print(json.dumps({
            "ok": False,
            "execute": args.execute,
            "window_start": f"{window_start:%Y-%m-%d %H:%M:%S}",
            "window_end": f"{window_end:%Y-%m-%d %H:%M:%S}",
            "validation": validation,
        }, ensure_ascii=False, indent=2))
        return 2 if args.strict and validation["warnings"] else 1

    output_dir = Path(args.output_dir) if args.output_dir else Path(tempfile.mkdtemp(prefix="loop-half-hour-report-"))
    label = f"{window_start:%Y%m%d%H%M}-{window_end:%H%M}"
    selected_path = output_dir / f"tasks-{args.loop_name}-{label}.json"
    write_rows(selected_rows, selected_path)
    push_result = run_push(args, selected_path, window_start, window_end)
    report = {
        "ok": True,
        "execute": args.execute,
        "window_start": f"{window_start:%Y-%m-%d %H:%M:%S}",
        "window_end": f"{window_end:%Y-%m-%d %H:%M:%S}",
        "filter_window": args.filter_window,
        "input_rows": len(rows),
        "reported_rows": len(selected_rows),
        "selected_tasks_file": str(selected_path),
        "validation": validation,
        "push_result": push_result,
    }
    report_path = output_dir / f"report-{args.loop_name}-{label}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**report, "report_file": str(report_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
