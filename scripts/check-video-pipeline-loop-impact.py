#!/usr/bin/env python3
"""Detect whether video-pipeline-tracker integration impacts the Liuxinyu loop."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LOOP_ROOT = "/Users/xinyuliu/Desktop/work/barry-video"
LOOP_ERROR_PATTERNS = (
    "Traceback",
    "SyntaxError",
    "Permission denied",
    "No space left",
    "Cannot allocate memory",
    "Killed",
    "command not found",
    "tracker command failed",
    "tracker push_round_result 失败",
    "tracker pull_strategy_bundle 失败",
    "tracker claim_strategy 失败",
)


def shell(cmd: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-lc", cmd], text=True, capture_output=True, timeout=timeout, check=False)


def tail_file(path: Path, lines: int = 120) -> str:
    if not path.exists():
        return ""
    proc = shell(f"tail -n {lines} {str(path)!r}", timeout=20)
    return proc.stdout


def stat_age(path: Path) -> int | None:
    if not path.exists():
        return None
    return int(datetime.now().timestamp() - path.stat().st_mtime)


def read_config(loop_root: Path) -> dict[str, Any]:
    try:
        payload = json.loads((loop_root / "conf/video_pipeline_tracker.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def json_url(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=8) as resp:
        data = json.load(resp)
    return data if isinstance(data, dict) else {}


def main() -> int:
    loop_root = Path(os.getenv("LOOP_ROOT", DEFAULT_LOOP_ROOT)).expanduser()
    config = read_config(loop_root)
    api_base = os.getenv("API_BASE", str(config.get("api_base") or "http://124.174.76.6")).rstrip("/")
    report_date = os.getenv("REPORT_DATE", datetime.now().strftime("%Y-%m-%d"))
    health_dir = loop_root / "runtime/video-pipeline-tracker/impact-health"
    health_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    def add(name: str, status: str, detail: str = "") -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    def fail(name: str, detail: str) -> None:
        errors.append(detail)
        add(name, "fail", detail)

    def warn(name: str, detail: str) -> None:
        warnings.append(detail)
        add(name, "warn", detail)

    def passed(name: str, detail: str = "") -> None:
        add(name, "pass", detail)

    continuous_dir = loop_root / f"runtime/continuous-loop/{report_date}"
    task_files = [p for p in continuous_dir.glob("*/*/tasks.json") if p.is_file() and p.stat().st_size > 0]

    proc = shell("ps -eo pid,etimes,cmd | grep -E 'run-dual-line-supervisor|run-drama-line-worker' | grep -v grep || true")
    process_lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if process_lines:
        passed("continuous_loop_process_alive", " | ".join(process_lines[:5]))
    elif task_files:
        passed("continuous_loop_process_alive", f"no active process now; today already has tracker artifacts={len(task_files)}")
    else:
        warn("continuous_loop_process_alive", "no run-dual-line-supervisor/run-drama-line-worker process found")

    proc = shell("ps -eo pid,etimes,cmd | grep -E 'report-video-pipeline|check-video-pipeline|push-loop-round-to-tracker' | grep -v grep || true")
    stuck = []
    for line in proc.stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) < 3:
            continue
        pid, etimes, cmd = parts
        try:
            age = int(etimes)
        except ValueError:
            continue
        if age > 600:
            stuck.append(f"pid={pid} age={age}s cmd={cmd}")
    if stuck:
        fail("tracker_process_not_stuck", "; ".join(stuck[:5]))
    else:
        passed("tracker_process_not_stuck", proc.stdout.strip())

    worker_logs = sorted(continuous_dir.glob("*/worker.log"))
    if worker_logs:
        passed("worker_logs_exist", f"{continuous_dir} logs={len(worker_logs)}")
    else:
        warn("worker_logs_exist", f"no worker.log under {continuous_dir}")

    stale_logs = []
    fresh_logs = 0
    matched_errors = []
    for log in worker_logs:
        age = stat_age(log)
        if age is not None and age > 7200:
            stale_logs.append(f"{log.parent.name}: age={age}s")
        elif age is not None:
            fresh_logs += 1
        tail = tail_file(log)
        matched = [pattern for pattern in LOOP_ERROR_PATTERNS if pattern in tail]
        if matched:
            matched_errors.append(f"{log}: {', '.join(matched)}")
    if stale_logs and fresh_logs:
        passed("worker_logs_recent", f"fresh_logs={fresh_logs}; completed_or_idle_lines={'; '.join(stale_logs[:8])}")
    elif stale_logs:
        warn("worker_logs_recent", "; ".join(stale_logs[:8]))
    elif worker_logs:
        passed("worker_logs_recent")
    if matched_errors:
        fail("worker_logs_no_tracker_errors", "; ".join(matched_errors[:8]))
    elif worker_logs:
        passed("worker_logs_no_tracker_errors")

    if task_files:
        passed("tracker_task_artifacts_exist", f"tasks={len(task_files)}")
    else:
        warn("tracker_task_artifacts_exist", f"no tracker task artifacts under {continuous_dir}")

    half_hour_dir = loop_root / f"runtime/video-pipeline-tracker/{report_date}/half-hour-reports"
    reports = sorted(half_hour_dir.glob("report-*.json"))
    if reports:
        latest = max(reports, key=lambda p: p.stat().st_mtime)
        age = stat_age(latest)
        if age is not None and age <= 4200:
            passed("half_hour_report_fresh", f"{latest} age={age}s")
        else:
            warn("half_hour_report_fresh", f"{latest} age={age}s")
    else:
        warn("half_hour_report_fresh", f"no report under {half_hour_dir}")

    try:
        health = json_url(f"{api_base}/api/health")
        if health.get("ok") is True:
            passed("dashboard_api_still_healthy")
        else:
            fail("dashboard_api_still_healthy", json.dumps(health, ensure_ascii=False))
    except Exception as exc:
        fail("dashboard_api_still_healthy", repr(exc))

    proc = shell("df -P / | awk 'NR==2 {print $5, $4}'")
    out = proc.stdout.strip().split()
    if len(out) >= 2:
        used_pct = int(out[0].rstrip("%"))
        avail_kb = int(out[1])
        if used_pct >= 90 or avail_kb < 5 * 1024 * 1024:
            fail("disk_space_safe", f"used={used_pct}% avail_kb={avail_kb}")
        else:
            passed("disk_space_safe", f"used={used_pct}% avail_kb={avail_kb}")
    else:
        warn("disk_space_safe", "could not parse df output")

    latest_skill_health = loop_root / "runtime/video-pipeline-tracker/health/latest-health.json"
    if latest_skill_health.exists():
        try:
            skill_health = json.loads(latest_skill_health.read_text(encoding="utf-8"))
        except Exception:
            skill_health = {}
        if skill_health.get("status") == "fail":
            fail("tracker_health_not_failing", str(latest_skill_health))
        elif skill_health.get("status") == "warn":
            warn("tracker_health_not_failing", str(latest_skill_health))
        elif skill_health:
            passed("tracker_health_not_failing", str(latest_skill_health))
        else:
            warn("tracker_health_not_failing", f"invalid health file: {latest_skill_health}")
    else:
        warn("tracker_health_not_failing", f"missing {latest_skill_health}")

    status = "fail" if errors else ("warn" if warnings else "ok")
    payload = {
        "ok": status == "ok",
        "status": status,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "report_date": report_date,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }
    latest_json = health_dir / "latest-impact.json"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (health_dir / "impact.log").open("a", encoding="utf-8") as f:
        f.write(f"[{payload['checked_at']}] status={status} errors={len(errors)} warnings={len(warnings)} latest={latest_json}\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
