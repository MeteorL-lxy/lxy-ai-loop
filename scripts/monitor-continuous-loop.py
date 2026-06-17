#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATE_ROOT = ROOT_DIR / "runtime" / "continuous-loop"
LINE_ORDER = [
    "realtime",
    "realtime_single",
    "realtime_day",
    "creative_list",
    "creative_list_day",
    "ordinary",
    "fbhot_test",
    "yourchannel",
    "recent_order",
]
LINE_PATTERN = "|".join(LINE_ORDER)

ROUND_START_RE = re.compile(
    rf"^\[(?P<ts>[^\]]+)\]\s+(?P<label>(?P<line>{LINE_PATTERN})-round(?P<round>\d+))\s+开始：(?P<details>.*)$"
)
ROUND_DONE_RE = re.compile(
    rf"^\[(?P<ts>[^\]]+)\]\s+(?P<label>(?P<line>{LINE_PATTERN})-round(?P<round>\d+))\s+完成：成功\s+(?P<success>\d+)，失败\s+(?P<failed>\d+)，处理中\s+(?P<processing>\d+)，未提交\s+(?P<unsubmitted>\d+)。$"
)
ROUND_ERROR_RE = re.compile(
    rf"^\[(?P<ts>[^\]]+)\]\s+(?P<label>(?P<line>{LINE_PATTERN})-round(?P<round>\d+))\s+命令返回非零（rc=(?P<rc>-?\d+)）"
)
HEARTBEAT_RE = re.compile(r"^\[heartbeat\]\s+(?P<stage>.+)$")
WORKER_EXIT_RE = re.compile(rf"^\[(?P<ts>[^\]]+)\]\s+line=(?P<line>{LINE_PATTERN})\s+exited code=(?P<code>-?\d+);")
ACCOUNT_EMPTY_RE = re.compile(rf"^\[(?P<ts>[^\]]+)\]\s+(?P<line>{LINE_PATTERN})\s+选账号失败：账号池\s+(?P<pool>\S+)\s+没有可用账号；")
TARGET_RESET_RE = re.compile(rf"^\[(?P<ts>[^\]]+)\]\s+(?P<line>{LINE_PATTERN})\s+达标标签已重置：(?P<details>.+)$")
TARGET_STOP_RE = re.compile(
    rf"^\[(?P<ts>[^\]]+)\]\s+(?P<line>{LINE_PATTERN})\s+已达成账号目标并停止：账号池=(?P<pool>\S+)，账号日目标=(?P<target>\d+)，(?P<details>.+)$"
)


@dataclass
class LineStatus:
    line_name: str
    state: str = "未运行"
    current_round: str = "-"
    latest_stage: str = "-"
    latest_stage_age: str = "-"
    last_summary: str = "-"
    note: str = ""
    last_update: str = "-"
    target_reached: bool = False


def _tail_lines(path: Path, limit: int = 300) -> list[str]:
    if not path.exists():
        return []
    queue: deque[str] = deque(maxlen=limit)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            queue.append(line.rstrip("\n"))
    return list(queue)


def _safe_age_text(ts_text: str) -> str:
    if not ts_text or ts_text == "-":
        return "-"
    try:
        then = datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"
    delta = datetime.now() - then
    total = max(0, int(delta.total_seconds()))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _read_latest_summary(run_dir: Path) -> str:
    summaries = sorted(run_dir.glob("round*.summary"))
    if not summaries:
        return "-"
    latest = summaries[-1]
    values: dict[str, str] = {}
    for line in latest.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    requested = values.get("requested_count", "0")
    success = values.get("success_count", "0")
    failed = values.get("failed_count", "0")
    unsubmitted = values.get("unsubmitted_count", "0")
    status_label = values.get("status_label", "-")
    return f"{latest.stem}: {status_label} / 请求 {requested} / 成功 {success} / 失败 {failed} / 未提交 {unsubmitted}"


def _parse_line_status(line_name: str, *, state_root: Path, day: str) -> LineStatus:
    status = LineStatus(line_name=line_name)
    forever_log = state_root / f"forever_{line_name}.log"
    worker_log = state_root / day / line_name / "worker.log"
    run_dir = state_root / day / line_name

    forever_lines = _tail_lines(forever_log)
    worker_lines = _tail_lines(worker_log)
    latest_start: tuple[str, str] | None = None
    latest_done: tuple[str, str, str, str, str] | None = None
    latest_error: tuple[str, str] | None = None
    latest_exit: tuple[str, str] | None = None
    latest_empty: tuple[str, str] | None = None
    latest_reset: tuple[str, str] | None = None
    latest_target_stop: tuple[str, str, str] | None = None

    for line in forever_lines:
        match = ROUND_START_RE.match(line)
        if match and match.group("line") == line_name:
            latest_start = (match.group("ts"), match.group("label"))
            continue
        match = ROUND_DONE_RE.match(line)
        if match and match.group("line") == line_name:
            latest_done = (
                match.group("ts"),
                match.group("label"),
                match.group("success"),
                match.group("failed"),
                match.group("unsubmitted"),
            )
            continue
        match = ROUND_ERROR_RE.match(line)
        if match and match.group("line") == line_name:
            latest_error = (match.group("ts"), f"{match.group('label')} rc={match.group('rc')}")
            continue
        match = WORKER_EXIT_RE.match(line)
        if match and match.group("line") == line_name:
            latest_exit = (match.group("ts"), match.group("code"))
            continue
        match = ACCOUNT_EMPTY_RE.match(line)
        if match and match.group("line") == line_name:
            latest_empty = (match.group("ts"), match.group("pool"))
            continue
        match = TARGET_RESET_RE.match(line)
        if match and match.group("line") == line_name:
            latest_reset = (match.group("ts"), match.group("details"))
            continue
        match = TARGET_STOP_RE.match(line)
        if match and match.group("line") == line_name:
            latest_target_stop = (match.group("ts"), match.group("pool"), match.group("details"))
            continue

    latest_heartbeat_line = "-"
    latest_heartbeat_ts = "-"
    for raw_line in reversed(worker_lines):
        match = HEARTBEAT_RE.match(raw_line)
        if match:
            latest_heartbeat_line = match.group("stage")
            latest_heartbeat_ts = datetime.fromtimestamp(worker_log.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            break

    status.latest_stage = latest_heartbeat_line
    status.latest_stage_age = _safe_age_text(latest_heartbeat_ts)
    status.last_summary = _read_latest_summary(run_dir)

    if latest_start:
        status.current_round = latest_start[1]
        status.last_update = latest_start[0]
        status.state = "执行中"
    if latest_done and latest_start:
        if latest_done[1] == latest_start[1]:
            done_ts = latest_done[0]
            start_ts = latest_start[0]
            try:
                if datetime.strptime(done_ts, "%Y-%m-%d %H:%M:%S") >= datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S"):
                    status.state = "已完成"
                    status.current_round = latest_done[1]
                    status.last_update = latest_done[0]
                    status.note = f"成功 {latest_done[2]} / 失败 {latest_done[3]} / 未提交 {latest_done[4]}"
            except Exception:
                pass
    if latest_error and (not status.note):
        status.note = f"最近一轮命令非零：{latest_error[1]}"
    if latest_target_stop:
        status.target_reached = True
        status.state = "已完成"
        status.last_update = latest_target_stop[0]
        status.note = f"已达成账号目标并停止：{latest_target_stop[1]}"
    if latest_empty:
        status.note = f"账号池无可用账号：{latest_empty[1]}"
        if line_name == "realtime":
            status.state = "等待重置/空闲"
        else:
            status.state = "空闲"
        status.last_update = latest_empty[0]
        if status.target_reached:
            status.note = f"{status.note}；已达成账号目标"
    if latest_reset:
        extra = f"；最近重置：{latest_reset[0]}"
        status.note = f"{status.note}{extra}" if status.note else f"最近重置：{latest_reset[0]}"
    if latest_exit and status.state == "未运行":
        status.state = f"已退出(code={latest_exit[1]})"
        status.last_update = latest_exit[0]

    return status


def _parse_line_names(raw: str) -> list[str]:
    if not str(raw or "").strip():
        return list(LINE_ORDER)
    values = []
    for item in str(raw).split(","):
        normalized = str(item or "").strip().lower()
        if not normalized:
            continue
        if normalized not in LINE_ORDER:
            raise ValueError(f"unsupported line name: {normalized}")
        if normalized not in values:
            values.append(normalized)
    return values or list(LINE_ORDER)


def _render_report(*, state_root: Path, day: str, line_names: list[str]) -> tuple[str, list[LineStatus]]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[{now}] continuous-loop 状态", ""]
    statuses: list[LineStatus] = []
    for line_name in line_names:
        status = _parse_line_status(line_name, state_root=state_root, day=day)
        statuses.append(status)
        lines.extend(
            [
                f"{line_name} 线",
                f"- 状态：{status.state}",
                f"- 当前轮次：{status.current_round}",
                f"- 当前阶段：{status.latest_stage}",
                f"- 阶段更新距今：{status.latest_stage_age}",
                f"- 最近汇总：{status.last_summary}",
                f"- 备注：{status.note or '-'}",
                "",
            ]
        )
    lines.append(f"状态目录：{state_root / day}")
    return "\n".join(lines), statuses


def _all_target_reached(statuses: list[LineStatus]) -> bool:
    return bool(statuses) and all(item.target_reached for item in statuses)


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor Barry Video continuous dual-line loop status.")
    parser.add_argument("--interval-seconds", type=int, default=300, help="Refresh interval in seconds.")
    parser.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT), help="Continuous loop state root.")
    parser.add_argument("--day", default=datetime.now().strftime("%Y-%m-%d"), help="State day directory (YYYY-MM-DD).")
    parser.add_argument("--once", action="store_true", help="Print one report and exit.")
    parser.add_argument("--output-file", default="", help="Optional file to append reports to.")
    parser.add_argument("--lines", default=",".join(LINE_ORDER), help="Comma-separated line names to monitor.")
    parser.add_argument("--exit-when-all-target-reached", action="store_true", help="Exit when all monitored lines have reached account targets.")
    args = parser.parse_args()

    state_root = Path(args.state_root).expanduser().resolve()
    output_path = Path(args.output_file).expanduser().resolve() if str(args.output_file).strip() else None
    interval = max(5, int(args.interval_seconds or 300))
    line_names = _parse_line_names(args.lines)

    while True:
        report, statuses = _render_report(state_root=state_root, day=args.day, line_names=line_names)
        print(report, flush=True)
        print("", flush=True)
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("a", encoding="utf-8") as handle:
                handle.write(report + "\n\n")
        if args.once:
            return 0
        if args.exit_when_all_target_reached and _all_target_reached(statuses):
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
