#!/usr/bin/env python3
"""Health check for the Liuxinyu video-pipeline-tracker integration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LOOP_ROOT = "/Users/xinyuliu/Desktop/work/barry-video"


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=merged_env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def tail(text: str, max_chars: int = 1200) -> str:
    text = text.strip()
    return text[-max_chars:] if len(text) > max_chars else text


def load_config(loop_root: Path) -> dict[str, Any]:
    path = loop_root / "conf/video_pipeline_tracker.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_json_url(url: str, timeout: int = 8) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        data = json.load(resp)
    return data if isinstance(data, dict) else {}


def last_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    last: dict[str, Any] = {}
    index = 0
    while index < len(text):
        next_index = text.find("{", index)
        if next_index < 0:
            break
        try:
            parsed, end = decoder.raw_decode(text[next_index:])
        except json.JSONDecodeError:
            index = next_index + 1
            continue
        if isinstance(parsed, dict):
            last = parsed
        index = next_index + max(end, 1)
    return last


def latest_file(pattern_dir: Path, glob_pattern: str) -> Path | None:
    files = [p for p in pattern_dir.glob(glob_pattern) if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def main() -> int:
    loop_root = Path(os.getenv("LOOP_ROOT", DEFAULT_LOOP_ROOT)).expanduser()
    config = load_config(loop_root)
    tool_dir = Path(os.getenv("TOOL_DIR", str(loop_root / "tools/video-pipeline-tracker")))
    api_base = os.getenv("API_BASE", str(config.get("api_base") or "http://124.174.76.6")).rstrip("/")
    owner = os.getenv("OWNER", str(config.get("owner") or "刘心雨"))
    loop_name = os.getenv("LOOP_NAME", str(config.get("loop_name") or "liuxinyu-ai-loop"))
    report_date = os.getenv("REPORT_DATE", datetime.now().strftime("%Y-%m-%d"))
    health_dir = loop_root / "runtime/video-pipeline-tracker/health"
    health_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    def add_check(name: str, status: str, detail: str = "") -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    def fail(name: str, detail: str) -> None:
        errors.append(detail)
        add_check(name, "fail", detail)

    def warn(name: str, detail: str) -> None:
        warnings.append(detail)
        add_check(name, "warn", detail)

    def passed(name: str, detail: str = "") -> None:
        add_check(name, "pass", detail)

    if str(config.get("enabled") or "").lower() in {"1", "true", "yes", "on"}:
        passed("tracker_enabled", str(loop_root / "conf/video_pipeline_tracker.json"))
    else:
        fail("tracker_enabled", "conf/video_pipeline_tracker.json is missing or disabled")

    if owner and loop_name:
        passed("owner_loop_configured", f"owner={owner} loop_name={loop_name}")
    else:
        fail("owner_loop_configured", "missing owner or loop_name")

    report_wrapper = loop_root / "scripts/report-video-pipeline-half-hour.sh"
    if report_wrapper.exists() and os.access(report_wrapper, os.X_OK):
        passed("report_wrapper_exists", str(report_wrapper))
    else:
        fail("report_wrapper_exists", f"missing or not executable: {report_wrapper}")

    required_scripts = [
        tool_dir / "scripts/validate_loop_payload.py",
        tool_dir / "scripts/report_half_hour_loop.py",
        tool_dir / "scripts/push_loop_result.py",
        tool_dir / "scripts/pull_dashboard_strategy.py",
        tool_dir / "scripts/claim_strategy_binding.py",
        loop_root / "scripts/push-loop-round-to-tracker.py",
    ]
    missing = [str(p) for p in required_scripts if not p.exists()]
    if missing:
        fail("tracker_scripts_exist", "missing: " + ", ".join(missing))
    else:
        passed("tracker_scripts_exist", str(tool_dir / "scripts"))

    proc = run([sys.executable, "-m", "py_compile", *map(str, required_scripts)], timeout=60)
    if proc.returncode == 0:
        passed("python_compile")
    else:
        fail("python_compile", tail(proc.stderr or proc.stdout))

    proc = run(["bash", "-n", str(report_wrapper)], timeout=30)
    if proc.returncode == 0:
        passed("wrapper_bash_syntax")
    else:
        fail("wrapper_bash_syntax", tail(proc.stderr or proc.stdout))

    try:
        health = load_json_url(f"{api_base}/api/health")
        if health.get("ok") is True:
            passed("dashboard_api_health", f"{api_base}/api/health")
        else:
            fail("dashboard_api_health", json.dumps(health, ensure_ascii=False))
    except Exception as exc:
        fail("dashboard_api_health", repr(exc))

    continuous_dir = loop_root / f"runtime/continuous-loop/{report_date}"
    task_files = [p for p in continuous_dir.glob("*/*/tasks.json") if p.is_file() and p.stat().st_size > 0]
    context_files = [p for p in continuous_dir.glob("*/*/strategy-context.json") if p.is_file() and p.stat().st_size > 0]
    if task_files:
        passed("today_tracker_task_files_exist", f"{continuous_dir} files={len(task_files)}")
    else:
        warn("today_tracker_task_files_exist", f"no non-empty */*/tasks.json under {continuous_dir}")
    if context_files:
        passed("today_strategy_context_exists", f"{continuous_dir} files={len(context_files)}")
    else:
        warn("today_strategy_context_exists", f"no strategy-context.json under {continuous_dir}")

    report_dir = loop_root / f"runtime/video-pipeline-tracker/{report_date}/half-hour-reports"
    latest_report = latest_file(report_dir, "report-*.json")
    if latest_report:
        age_seconds = int(datetime.now().timestamp() - latest_report.stat().st_mtime)
        if age_seconds <= 4200:
            passed("latest_report_fresh", f"{latest_report} age={age_seconds}s")
        else:
            warn("latest_report_fresh", f"latest report stale: {latest_report} age={age_seconds}s")
    else:
        warn("latest_report_fresh", f"no report-*.json under {report_dir}")

    dry_run_dir = health_dir / f"dry-run-{report_date}"
    dry_run_dir.mkdir(parents=True, exist_ok=True)
    proc = run(
        ["bash", "-lc", f"REPORT_DATE={report_date} EXECUTE=0 OUT_DIR={dry_run_dir} ./scripts/report-video-pipeline-half-hour.sh"],
        cwd=loop_root,
        timeout=180,
    )
    (health_dir / "dry-run.stdout").write_text(proc.stdout, encoding="utf-8")
    (health_dir / "dry-run.stderr").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode == 0:
        try:
            last_json = last_json_object(proc.stdout)
            if last_json.get("ok") is True and last_json.get("execute") is False:
                validation = last_json.get("validation") if isinstance(last_json.get("validation"), dict) else {}
                if validation.get("errors"):
                    fail("dry_run_report", "validation errors: " + json.dumps(validation.get("errors"), ensure_ascii=False))
                else:
                    passed("dry_run_report", str(health_dir / "dry-run.stdout"))
            else:
                fail("dry_run_report", "dry-run output is not ok")
        except Exception as exc:
            fail("dry_run_report", f"dry-run JSON assertion failed: {exc}; stdout={tail(proc.stdout)}")
    else:
        fail("dry_run_report", tail(proc.stderr or proc.stdout))

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
    latest_json = health_dir / "latest-health.json"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (health_dir / "health.log").open("a", encoding="utf-8") as f:
        f.write(f"[{payload['checked_at']}] status={status} errors={len(errors)} warnings={len(warnings)} latest={latest_json}\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
