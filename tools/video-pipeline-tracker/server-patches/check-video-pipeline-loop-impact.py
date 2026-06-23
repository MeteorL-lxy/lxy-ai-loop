#!/usr/bin/env python3
"""Detect whether video-pipeline-tracker integration impacts the Steven loop."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


LOOP_ERROR_PATTERNS = (
    "Traceback",
    "SyntaxError",
    "Permission denied",
    "No space left",
    "Cannot allocate memory",
    "Killed",
    "command not found",
    "report-video-pipeline-half-hour.sh: line",
    "check-video-pipeline-tracker-health.py",
)


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def shell(cmd: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run(["bash", "-lc", cmd], timeout=timeout)


def tail_file(path: Path, lines: int = 120) -> str:
    if not path.exists():
        return ""
    proc = shell(f"tail -n {lines} {str(path)!r}", timeout=20)
    return proc.stdout


def stat_age(path: Path) -> int | None:
    if not path.exists():
        return None
    return int(datetime.now().timestamp() - path.stat().st_mtime)


def latest_file(directory: Path, pattern: str) -> Path | None:
    files = [p for p in directory.glob(pattern) if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def json_url(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=8) as resp:
        data = json.load(resp)
    return data if isinstance(data, dict) else {}


def main() -> int:
    loop_root = Path(os.getenv("LOOP_ROOT", "/opt/steven-jiao-ai-loop"))
    api_base = os.getenv("API_BASE", "http://127.0.0.1:8770").rstrip("/")
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

    # 1. Main loop service and scheduler process must stay alive.
    proc = shell("systemctl is-active steven-jiao-ai-loop.service 2>/dev/null || true")
    if proc.stdout.strip() == "active":
        passed("steven_service_active")
    else:
        fail("steven_service_active", f"service inactive: {proc.stdout.strip() or proc.stderr.strip()}")

    proc = shell("ps -eo pid,etimes,cmd | grep -E 'run-daily-loop-scheduler|run-server-daily-loop' | grep -v grep || true")
    scheduler_lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if scheduler_lines:
        passed("main_scheduler_process_alive", " | ".join(scheduler_lines[:3]))
    else:
        fail("main_scheduler_process_alive", "no run-daily-loop-scheduler/run-server-daily-loop process found")

    pid_file = loop_root / f"runtime/daily-loop/{report_date}/scheduler.pid"
    if pid_file.exists():
        pid = pid_file.read_text(encoding="utf-8").strip()
        proc = shell(f"test -n {pid!r} && kill -0 {pid} 2>/dev/null")
        if proc.returncode == 0:
            passed("scheduler_pid_alive", pid)
        else:
            fail("scheduler_pid_alive", f"scheduler.pid exists but pid is not alive: {pid}")
    else:
        warn("scheduler_pid_alive", f"missing scheduler pid file: {pid_file}")

    # 2. Tracker scripts must not leave stuck long-running processes.
    proc = shell("ps -eo pid,etimes,cmd | grep -E 'report-video-pipeline|check-video-pipeline' | grep -v grep || true")
    stuck = []
    for line in proc.stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) >= 3:
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

    # 3. Scheduler artifacts should exist and not show integration-related shell/runtime failures.
    daily_dir = loop_root / f"runtime/daily-loop/{report_date}"
    scheduler_log = daily_dir / "scheduler.log"
    if scheduler_log.exists():
        age = stat_age(scheduler_log)
        detail = f"{scheduler_log} age={age}s"
        if age is not None and age > 7200:
            warn("scheduler_log_recent", detail)
        else:
            passed("scheduler_log_recent", detail)
        tail = tail_file(scheduler_log)
        matched = [pattern for pattern in LOOP_ERROR_PATTERNS if pattern in tail]
        if matched:
            fail("scheduler_log_no_integration_errors", "matched patterns: " + ", ".join(matched))
        else:
            passed("scheduler_log_no_integration_errors")
    else:
        warn("scheduler_log_recent", f"missing scheduler log: {scheduler_log}")

    summaries = sorted(daily_dir.glob("round*.summary"))
    round_jsons = sorted(daily_dir.glob("round*.json"))
    if summaries and round_jsons:
        passed("round_artifacts_exist", f"summaries={len(summaries)} jsons={len(round_jsons)}")
    else:
        warn("round_artifacts_exist", f"summaries={len(summaries)} jsons={len(round_jsons)} in {daily_dir}")

    telemetry_dir = loop_root / f"runtime/telemetry/{report_date}"
    traces = [p for p in telemetry_dir.glob("round*.task_trace.jsonl") if p.is_file() and p.stat().st_size > 0]
    if traces:
        passed("telemetry_still_generated", f"{len(traces)} task_trace files")
    else:
        warn("telemetry_still_generated", f"no task_trace files under {telemetry_dir}")

    # 4. Tracker output should be fresh, but it should not be the only signal.
    report_dir = loop_root / f"runtime/video-pipeline-tracker/{report_date}/half-hour-reports"
    latest_report = latest_file(report_dir, "report-*.json")
    if latest_report:
        age = stat_age(latest_report)
        if age is not None and age <= 4200:
            passed("tracker_latest_report_fresh", f"{latest_report} age={age}s")
        else:
            warn("tracker_latest_report_fresh", f"{latest_report} age={age}s")
    else:
        warn("tracker_latest_report_fresh", f"no report under {report_dir}")

    tracker_log = loop_root / "runtime/video-pipeline-tracker/half-hour-cron.log"
    tracker_tail = tail_file(tracker_log, lines=80)
    if tracker_tail and re.search(r"(Traceback|SyntaxError|Permission denied|No space left|command not found)", tracker_tail):
        fail("tracker_cron_log_clean", "tracker cron log contains runtime errors")
    else:
        passed("tracker_cron_log_clean", str(tracker_log))

    # 5. API and host resources should remain healthy.
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

    proc = shell("awk '{print $1,$2,$3}' /proc/loadavg")
    passed("load_average", proc.stdout.strip())

    latest_skill_health = loop_root / "runtime/video-pipeline-tracker/health/latest-health.json"
    skill_health = read_json(latest_skill_health)
    if skill_health:
        if skill_health.get("status") == "fail":
            fail("tracker_health_not_failing", str(latest_skill_health))
        elif skill_health.get("status") == "warn":
            warn("tracker_health_not_failing", str(latest_skill_health))
        else:
            passed("tracker_health_not_failing", str(latest_skill_health))
    else:
        warn("tracker_health_not_failing", f"missing or unreadable {latest_skill_health}")

    status = "fail" if errors else ("warn" if warnings else "ok")
    payload = {
        "ok": status == "ok",
        "status": status,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "report_date": report_date,
        "purpose": "detect whether video-pipeline-tracker integration is impacting the original loop",
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
