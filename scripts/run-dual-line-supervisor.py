#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
TMP_DIR = ROOT_DIR / "runtime" / "continuous-loop"
TMP_DIR.mkdir(parents=True, exist_ok=True)
PYTHON = sys.executable or "python3"
WORKER = ROOT_DIR / "scripts" / "run-drama-line-worker.py"


def _log(message: str) -> None:
    print(f"[{time.strftime('%F %T')}] {message}", flush=True)


def _env(name: str, default: str) -> str:
    return str(os.getenv(name) or default).strip() or default


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _current_day() -> str:
    return time.strftime("%F")


WINDOW_PAUSED_EXIT_CODE = 75
DAY_WINDOW = _env("BARRY_LOOP_DAY_WINDOW", "10:00-18:00")
NIGHT_WINDOW = _env("BARRY_LOOP_NIGHT_WINDOW", "18:00-12:00")
TIME_WINDOW_ENABLED = _truthy(os.getenv("BARRY_LOOP_TIME_WINDOW_ENABLED", "1"))
SUPERVISOR_POLL_SECONDS = max(1, int(_env("BARRY_LOOP_SUPERVISOR_POLL_SECONDS", "5")))
SUPERVISOR_SPAWN_STAGGER_SECONDS = max(0, int(_env("BARRY_LOOP_SUPERVISOR_SPAWN_STAGGER_SECONDS", "5")))


def _parse_hhmm(value: str) -> int:
    hour_text, minute_text = str(value or "").strip().split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid HH:MM value: {value}")
    return hour * 60 + minute


def _parse_window(value: str) -> tuple[int, int]:
    start_text, end_text = str(value or "").strip().split("-", 1)
    return _parse_hhmm(start_text), _parse_hhmm(end_text)


def _current_minute() -> int:
    now = datetime.now()
    return now.hour * 60 + now.minute


def _window_contains(window: str, minute: int | None = None) -> bool:
    if not TIME_WINDOW_ENABLED:
        return True
    raw = str(window or "").strip()
    if not raw:
        return True
    try:
        start, end = _parse_window(raw)
    except Exception:
        _log(f"时间窗配置无效：{raw}，按全天可运行处理。")
        return True
    current = _current_minute() if minute is None else int(minute)
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _line_in_window(config: dict[str, object]) -> bool:
    return _window_contains(str(config.get("window") or ""))


LINE_CONFIGS = {
    "realtime": {
        "enabled": _env("BARRY_LOOP_REALTIME_ENABLED", "1"),
        "window": _env("BARRY_LOOP_REALTIME_WINDOW", NIGHT_WINDOW),
        "pool": _env("BARRY_LOOP_REALTIME_ACCOUNT_POOL", "facebook_drama_realtime_pool"),
        "count": _env("BARRY_LOOP_REALTIME_COUNT", "0"),
        "flywheel_config": str(os.getenv("BARRY_LOOP_REALTIME_FLYWHEEL_CONFIG") or "").strip(),
        "fb_heat_signal_file": str(os.getenv("BARRY_LOOP_REALTIME_FB_HEAT_SIGNAL_FILE") or "").strip(),
        "realtime_enabled": _env("BARRY_LOOP_REALTIME_RANK_ENABLED", "1"),
        "realtime_material_only": _env("BARRY_LOOP_REALTIME_MATERIAL_ONLY", "1"),
        "creative_list_material_only": _env("BARRY_LOOP_REALTIME_CREATIVE_LIST_MATERIAL_ONLY", "0"),
        "sleep_seconds": _env("BARRY_LOOP_REALTIME_SLEEP_SECONDS", "20"),
        "idle_sleep_seconds": _env("BARRY_LOOP_REALTIME_IDLE_SLEEP_SECONDS", "300"),
        "error_sleep_seconds": _env("BARRY_LOOP_REALTIME_ERROR_SLEEP_SECONDS", "20"),
        "target_reset_sleep_seconds": _env("BARRY_LOOP_REALTIME_TARGET_RESET_SLEEP_SECONDS", "3600"),
        "log": TMP_DIR / "forever_realtime.log",
    },
    "realtime_single": {
        "enabled": _env("BARRY_LOOP_REALTIME_SINGLE_ENABLED", "0"),
        "window": _env("BARRY_LOOP_REALTIME_SINGLE_WINDOW", NIGHT_WINDOW),
        "pool": _env("BARRY_LOOP_REALTIME_SINGLE_ACCOUNT_POOL", "facebook_drama_realtime_single_pool"),
        "count": _env("BARRY_LOOP_REALTIME_SINGLE_COUNT", "0"),
        "flywheel_config": str(os.getenv("BARRY_LOOP_REALTIME_SINGLE_FLYWHEEL_CONFIG") or "conf/flywheel_realtime_single.yaml").strip(),
        "fb_heat_signal_file": str(os.getenv("BARRY_LOOP_REALTIME_SINGLE_FB_HEAT_SIGNAL_FILE") or "").strip(),
        "realtime_enabled": _env("BARRY_LOOP_REALTIME_SINGLE_RANK_ENABLED", "1"),
        "realtime_material_only": _env("BARRY_LOOP_REALTIME_SINGLE_MATERIAL_ONLY", "1"),
        "creative_list_material_only": _env("BARRY_LOOP_REALTIME_SINGLE_CREATIVE_LIST_MATERIAL_ONLY", "0"),
        "sleep_seconds": _env("BARRY_LOOP_REALTIME_SINGLE_SLEEP_SECONDS", "30"),
        "idle_sleep_seconds": _env("BARRY_LOOP_REALTIME_SINGLE_IDLE_SLEEP_SECONDS", "300"),
        "error_sleep_seconds": _env("BARRY_LOOP_REALTIME_SINGLE_ERROR_SLEEP_SECONDS", "20"),
        "wait_for_line": _env("BARRY_LOOP_REALTIME_SINGLE_WAIT_FOR_LINE", ""),
        "wait_for_line_pool": _env("BARRY_LOOP_REALTIME_SINGLE_WAIT_FOR_LINE_POOL", ""),
        "log": TMP_DIR / "forever_realtime_single.log",
    },
    "realtime_day": {
        "enabled": _env("BARRY_LOOP_REALTIME_DAY_ENABLED", "0"),
        "window": _env("BARRY_LOOP_REALTIME_DAY_WINDOW", DAY_WINDOW),
        "pool": _env("BARRY_LOOP_REALTIME_DAY_ACCOUNT_POOL", "facebook_drama_realtime_day_pool"),
        "count": _env("BARRY_LOOP_REALTIME_DAY_COUNT", "0"),
        "flywheel_config": str(os.getenv("BARRY_LOOP_REALTIME_DAY_FLYWHEEL_CONFIG") or "conf/flywheel_realtime_day.yaml").strip(),
        "fb_heat_signal_file": str(os.getenv("BARRY_LOOP_REALTIME_DAY_FB_HEAT_SIGNAL_FILE") or "").strip(),
        "realtime_enabled": _env("BARRY_LOOP_REALTIME_DAY_RANK_ENABLED", "1"),
        "realtime_material_only": _env("BARRY_LOOP_REALTIME_DAY_MATERIAL_ONLY", "1"),
        "creative_list_material_only": _env("BARRY_LOOP_REALTIME_DAY_CREATIVE_LIST_MATERIAL_ONLY", "0"),
        "sleep_seconds": _env("BARRY_LOOP_REALTIME_DAY_SLEEP_SECONDS", "20"),
        "idle_sleep_seconds": _env("BARRY_LOOP_REALTIME_DAY_IDLE_SLEEP_SECONDS", "300"),
        "error_sleep_seconds": _env("BARRY_LOOP_REALTIME_DAY_ERROR_SLEEP_SECONDS", "20"),
        "log": TMP_DIR / "forever_realtime_day.log",
    },
    "creative_list": {
        "enabled": _env("BARRY_LOOP_CREATIVE_LIST_ENABLED", "0"),
        "window": _env("BARRY_LOOP_CREATIVE_LIST_WINDOW", NIGHT_WINDOW),
        "pool": _env("BARRY_LOOP_CREATIVE_LIST_ACCOUNT_POOL", "facebook_drama_creative_list_pool"),
        "count": _env("BARRY_LOOP_CREATIVE_LIST_COUNT", "0"),
        "flywheel_config": str(os.getenv("BARRY_LOOP_CREATIVE_LIST_FLYWHEEL_CONFIG") or "conf/flywheel_creative_list.yaml").strip(),
        "fb_heat_signal_file": str(os.getenv("BARRY_LOOP_CREATIVE_LIST_FB_HEAT_SIGNAL_FILE") or "").strip(),
        "realtime_enabled": _env("BARRY_LOOP_CREATIVE_LIST_RANK_ENABLED", "0"),
        "realtime_material_only": _env("BARRY_LOOP_CREATIVE_LIST_MATERIAL_ONLY", "0"),
        "creative_list_material_only": _env("BARRY_LOOP_CREATIVE_LIST_MATERIAL_ONLY", "1"),
        "sleep_seconds": _env("BARRY_LOOP_CREATIVE_LIST_SLEEP_SECONDS", "45"),
        "idle_sleep_seconds": _env("BARRY_LOOP_CREATIVE_LIST_IDLE_SLEEP_SECONDS", "300"),
        "error_sleep_seconds": _env("BARRY_LOOP_CREATIVE_LIST_ERROR_SLEEP_SECONDS", "20"),
        "log": TMP_DIR / "forever_creative_list.log",
    },
    "creative_list_day": {
        "enabled": _env("BARRY_LOOP_CREATIVE_LIST_DAY_ENABLED", "0"),
        "window": _env("BARRY_LOOP_CREATIVE_LIST_DAY_WINDOW", DAY_WINDOW),
        "pool": _env("BARRY_LOOP_CREATIVE_LIST_DAY_ACCOUNT_POOL", "facebook_drama_creative_list_day_pool"),
        "count": _env("BARRY_LOOP_CREATIVE_LIST_DAY_COUNT", "0"),
        "flywheel_config": str(os.getenv("BARRY_LOOP_CREATIVE_LIST_DAY_FLYWHEEL_CONFIG") or "conf/flywheel_creative_list_day.yaml").strip(),
        "fb_heat_signal_file": str(os.getenv("BARRY_LOOP_CREATIVE_LIST_DAY_FB_HEAT_SIGNAL_FILE") or "").strip(),
        "realtime_enabled": _env("BARRY_LOOP_CREATIVE_LIST_DAY_RANK_ENABLED", "0"),
        "realtime_material_only": _env("BARRY_LOOP_CREATIVE_LIST_DAY_MATERIAL_ONLY", "0"),
        "creative_list_material_only": _env("BARRY_LOOP_CREATIVE_LIST_DAY_MATERIAL_ONLY", "1"),
        "sleep_seconds": _env("BARRY_LOOP_CREATIVE_LIST_DAY_SLEEP_SECONDS", "45"),
        "idle_sleep_seconds": _env("BARRY_LOOP_CREATIVE_LIST_DAY_IDLE_SLEEP_SECONDS", "300"),
        "error_sleep_seconds": _env("BARRY_LOOP_CREATIVE_LIST_DAY_ERROR_SLEEP_SECONDS", "20"),
        "log": TMP_DIR / "forever_creative_list_day.log",
    },
    "ordinary": {
        "enabled": _env("BARRY_LOOP_ORDINARY_ENABLED", "1"),
        "window": _env("BARRY_LOOP_ORDINARY_WINDOW", NIGHT_WINDOW),
        "pool": _env("BARRY_LOOP_ORDINARY_ACCOUNT_POOL", "facebook_drama_ordinary_pool"),
        "count": _env("BARRY_LOOP_ORDINARY_COUNT", "0"),
        "flywheel_config": str(os.getenv("BARRY_LOOP_ORDINARY_FLYWHEEL_CONFIG") or "").strip(),
        "fb_heat_signal_file": str(os.getenv("BARRY_LOOP_ORDINARY_FB_HEAT_SIGNAL_FILE") or "").strip(),
        "realtime_enabled": _env("BARRY_LOOP_ORDINARY_RANK_ENABLED", "0"),
        "realtime_material_only": _env("BARRY_LOOP_ORDINARY_MATERIAL_ONLY", "0"),
        "creative_list_material_only": _env("BARRY_LOOP_ORDINARY_CREATIVE_LIST_MATERIAL_ONLY", "0"),
        "sleep_seconds": _env("BARRY_LOOP_ORDINARY_SLEEP_SECONDS", "45"),
        "idle_sleep_seconds": _env("BARRY_LOOP_ORDINARY_IDLE_SLEEP_SECONDS", "300"),
        "error_sleep_seconds": _env("BARRY_LOOP_ORDINARY_ERROR_SLEEP_SECONDS", "20"),
        "log": TMP_DIR / "forever_ordinary.log",
    },
    "fbhot_test": {
        "enabled": _env("BARRY_LOOP_FBHOT_TEST_ENABLED", "1"),
        "window": _env("BARRY_LOOP_FBHOT_TEST_WINDOW", NIGHT_WINDOW),
        "pool": _env("BARRY_LOOP_FBHOT_TEST_ACCOUNT_POOL", "facebook_drama_fbhot_test_pool"),
        "count": _env("BARRY_LOOP_FBHOT_TEST_COUNT", "0"),
        "flywheel_config": str(os.getenv("BARRY_LOOP_FBHOT_TEST_FLYWHEEL_CONFIG") or "").strip(),
        "fb_heat_signal_file": str(os.getenv("BARRY_LOOP_FBHOT_TEST_FB_HEAT_SIGNAL_FILE") or "").strip(),
        "realtime_enabled": _env("BARRY_LOOP_FBHOT_TEST_RANK_ENABLED", "0"),
        "realtime_material_only": _env("BARRY_LOOP_FBHOT_TEST_MATERIAL_ONLY", "0"),
        "creative_list_material_only": _env("BARRY_LOOP_FBHOT_TEST_CREATIVE_LIST_MATERIAL_ONLY", "0"),
        "sleep_seconds": _env("BARRY_LOOP_FBHOT_TEST_SLEEP_SECONDS", "45"),
        "idle_sleep_seconds": _env("BARRY_LOOP_FBHOT_TEST_IDLE_SLEEP_SECONDS", "300"),
        "error_sleep_seconds": _env("BARRY_LOOP_FBHOT_TEST_ERROR_SLEEP_SECONDS", "20"),
        "log": TMP_DIR / "forever_fbhot_test.log",
    },
    "yourchannel": {
        "enabled": _env("BARRY_LOOP_YOURCHANNEL_ENABLED", "0"),
        "window": _env("BARRY_LOOP_YOURCHANNEL_WINDOW", DAY_WINDOW),
        "pool": _env("BARRY_LOOP_YOURCHANNEL_ACCOUNT_POOL", "facebook_drama_yourchannel_pool"),
        "count": _env("BARRY_LOOP_YOURCHANNEL_COUNT", "0"),
        "flywheel_config": str(os.getenv("BARRY_LOOP_YOURCHANNEL_FLYWHEEL_CONFIG") or "conf/flywheel_yourchannel.yaml").strip(),
        "fb_heat_signal_file": str(os.getenv("BARRY_LOOP_YOURCHANNEL_FB_HEAT_SIGNAL_FILE") or "").strip(),
        "realtime_enabled": _env("BARRY_LOOP_YOURCHANNEL_RANK_ENABLED", "0"),
        "realtime_material_only": _env("BARRY_LOOP_YOURCHANNEL_MATERIAL_ONLY", "0"),
        "creative_list_material_only": _env("BARRY_LOOP_YOURCHANNEL_CREATIVE_LIST_MATERIAL_ONLY", "0"),
        "sleep_seconds": _env("BARRY_LOOP_YOURCHANNEL_SLEEP_SECONDS", "45"),
        "idle_sleep_seconds": _env("BARRY_LOOP_YOURCHANNEL_IDLE_SLEEP_SECONDS", "300"),
        "error_sleep_seconds": _env("BARRY_LOOP_YOURCHANNEL_ERROR_SLEEP_SECONDS", "20"),
        "log": TMP_DIR / "forever_yourchannel.log",
    },
    "recent_order": {
        "enabled": _env("BARRY_LOOP_RECENT_ORDER_ENABLED", "0"),
        "window": _env("BARRY_LOOP_RECENT_ORDER_WINDOW", NIGHT_WINDOW),
        "pool": _env("BARRY_LOOP_RECENT_ORDER_ACCOUNT_POOL", "facebook_drama_recent_order_pool"),
        "count": _env("BARRY_LOOP_RECENT_ORDER_COUNT", "0"),
        "flywheel_config": str(os.getenv("BARRY_LOOP_RECENT_ORDER_FLYWHEEL_CONFIG") or "conf/flywheel_recent_order.yaml").strip(),
        "fb_heat_signal_file": str(os.getenv("BARRY_LOOP_RECENT_ORDER_FB_HEAT_SIGNAL_FILE") or "").strip(),
        "realtime_enabled": _env("BARRY_LOOP_RECENT_ORDER_RANK_ENABLED", "0"),
        "realtime_material_only": _env("BARRY_LOOP_RECENT_ORDER_MATERIAL_ONLY", "0"),
        "creative_list_material_only": _env("BARRY_LOOP_RECENT_ORDER_CREATIVE_LIST_MATERIAL_ONLY", "0"),
        "sleep_seconds": _env("BARRY_LOOP_RECENT_ORDER_SLEEP_SECONDS", "45"),
        "idle_sleep_seconds": _env("BARRY_LOOP_RECENT_ORDER_IDLE_SLEEP_SECONDS", "300"),
        "error_sleep_seconds": _env("BARRY_LOOP_RECENT_ORDER_ERROR_SLEEP_SECONDS", "20"),
        "log": TMP_DIR / "forever_recent_order.log",
    },
    "stardusttv": {
        "enabled": _env("BARRY_LOOP_STARDUSTTV_ENABLED", "1"),
        "window": _env("BARRY_LOOP_STARDUSTTV_WINDOW", NIGHT_WINDOW),
        "pool": _env("BARRY_LOOP_STARDUSTTV_ACCOUNT_POOL", "facebook_drama_stardusttv_pool"),
        "count": _env("BARRY_LOOP_STARDUSTTV_COUNT", "0"),
        "flywheel_config": str(os.getenv("BARRY_LOOP_STARDUSTTV_FLYWHEEL_CONFIG") or "conf/flywheel_stardusttv.yaml").strip(),
        "fb_heat_signal_file": str(os.getenv("BARRY_LOOP_STARDUSTTV_FB_HEAT_SIGNAL_FILE") or "").strip(),
        "realtime_enabled": _env("BARRY_LOOP_STARDUSTTV_RANK_ENABLED", "0"),
        "realtime_material_only": _env("BARRY_LOOP_STARDUSTTV_MATERIAL_ONLY", "0"),
        "creative_list_material_only": _env("BARRY_LOOP_STARDUSTTV_CREATIVE_LIST_MATERIAL_ONLY", "0"),
        "sleep_seconds": _env("BARRY_LOOP_STARDUSTTV_SLEEP_SECONDS", "45"),
        "idle_sleep_seconds": _env("BARRY_LOOP_STARDUSTTV_IDLE_SLEEP_SECONDS", "300"),
        "error_sleep_seconds": _env("BARRY_LOOP_STARDUSTTV_ERROR_SLEEP_SECONDS", "20"),
        "log": TMP_DIR / "forever_stardusttv.log",
    },
}


ROLLOVER_RESET_ENABLED = _truthy(os.getenv("BARRY_LOOP_DATE_ROLLOVER_RESET_ENABLED", "0"))


def _spawn_line(name: str, config: dict[str, object]) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["BARRY_LOOP_LINE_NAME"] = name
    env["BARRY_LOOP_ACCOUNT_POOL"] = str(config["pool"])
    env["BARRY_LOOP_COUNT"] = str(config.get("count") or "0")
    if str(config.get("flywheel_config") or "").strip():
        env["BARRY_LOOP_FLYWHEEL_CONFIG"] = str(config["flywheel_config"])
    if str(config.get("fb_heat_signal_file") or "").strip():
        env["BARRY_FB_HEAT_SIGNAL_FILE"] = str(config["fb_heat_signal_file"])
    env["BARRY_REALTIME_RANK_ENABLED"] = str(config["realtime_enabled"])
    env["BARRY_LOOP_REALTIME_MATERIAL_ONLY"] = str(config.get("realtime_material_only", "0"))
    env["BARRY_LOOP_CREATIVE_LIST_MATERIAL_ONLY"] = str(config.get("creative_list_material_only", "0"))
    env["BARRY_LOOP_LINE_SLEEP_SECONDS"] = str(config["sleep_seconds"])
    env["BARRY_LOOP_LINE_IDLE_SLEEP_SECONDS"] = str(config["idle_sleep_seconds"])
    env["BARRY_LOOP_LINE_ERROR_SLEEP_SECONDS"] = str(config["error_sleep_seconds"])
    env["BARRY_LOOP_ACTIVE_WINDOW"] = str(config.get("window") or "")
    if str(config.get("target_reset_sleep_seconds") or "").strip():
        env["BARRY_LOOP_LINE_TARGET_RESET_SLEEP_SECONDS"] = str(config["target_reset_sleep_seconds"])
    if str(config.get("wait_for_line") or "").strip():
        env["BARRY_LOOP_WAIT_FOR_LINE"] = str(config["wait_for_line"])
    if str(config.get("wait_for_line_pool") or "").strip():
        env["BARRY_LOOP_WAIT_FOR_LINE_POOL"] = str(config["wait_for_line_pool"])
    env.setdefault("BARRY_FEISHU_DAILY_LOOP_REPORT_PUSH", "0")
    env.setdefault("BARRY_FEISHU_DAILY_LOOP_ROUND_NOTICE_PUSH", "0")
    env.setdefault("BARRY_LOOP_STATE_ROOT", str(ROOT_DIR / "runtime" / "continuous-loop"))
    env.setdefault("BARRY_LOOP_REPORT_DIR", str(ROOT_DIR / "runtime" / "reports" / "continuous-test-summary"))

    log_path = Path(config["log"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8")
    handle.write(f"\n[{time.strftime('%F %T')}] spawn line={name}\n")
    handle.flush()
    proc = subprocess.Popen(
        [PYTHON, "-u", str(WORKER)],
        cwd=str(ROOT_DIR),
        env=env,
        stdout=handle,
        stderr=handle,
        text=True,
    )
    proc._barry_log_handle = handle  # type: ignore[attr-defined]
    return proc


def main() -> int:
    children: dict[str, subprocess.Popen[str]] = {}
    completed: set[str] = set()
    stopping = False
    generation_day = _current_day()
    waiting_for_rollover_logged = False
    enabled_lines = {
        name
        for name, config in LINE_CONFIGS.items()
        if str(config.get("enabled") or "0").strip().lower() in {"1", "true", "yes", "on"}
    }

    def _stop_children() -> None:
        for proc in children.values():
            if proc.poll() is None:
                proc.terminate()
        deadline = time.time() + 10
        for proc in children.values():
            if proc.poll() is None:
                try:
                    proc.wait(timeout=max(0.1, deadline - time.time()))
                except subprocess.TimeoutExpired:
                    proc.kill()
        for proc in children.values():
            handle = getattr(proc, "_barry_log_handle", None)
            if handle:
                handle.close()

    def _signal_handler(signum, frame):  # noqa: ANN001, ARG001
        nonlocal stopping
        stopping = True
        _log(f"收到信号 {signum}，准备停止 dual-line supervisor。")
        _stop_children()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    waiting_window_logged: set[str] = set()

    def _maybe_spawn_ready_lines(reason: str) -> None:
        spawned_count = 0
        for name, config in LINE_CONFIGS.items():
            if name not in enabled_lines or name in completed or name in children:
                continue
            if not _line_in_window(config):
                if name not in waiting_window_logged:
                    _log(f"{name} worker 等待时间窗 {config.get('window') or '全天'}，当前不启动。")
                    waiting_window_logged.add(name)
                continue
            waiting_window_logged.discard(name)
            if spawned_count > 0 and SUPERVISOR_SPAWN_STAGGER_SECONDS > 0:
                time.sleep(SUPERVISOR_SPAWN_STAGGER_SECONDS)
            children[name] = _spawn_line(name, config)
            spawned_count += 1
            _log(f"已启动 {name} worker，pid={children[name].pid}，原因={reason}，时间窗={config.get('window') or '全天'}。")

    for name, config in LINE_CONFIGS.items():
        if name not in enabled_lines:
            _log(f"{name} worker 已暂停，跳过启动。")
    _maybe_spawn_ready_lines("startup")

    while not stopping:
        time.sleep(SUPERVISOR_POLL_SECONDS)
        current_day = _current_day()
        if ROLLOVER_RESET_ENABLED and current_day != generation_day:
            generation_day = current_day
            waiting_for_rollover_logged = False
            completed.clear()
            _log("检测到跨 0 点：已进入新自然日，清空上一日达标状态并按新日期重新拉起已启用线路。")
            for name in list(children):
                proc = children[name]
                if proc.poll() is not None:
                    children.pop(name, None)
            _maybe_spawn_ready_lines("date-rollover")
        for name, config in LINE_CONFIGS.items():
            if name in completed:
                continue
            proc = children.get(name)
            if proc is None:
                continue
            code = proc.poll()
            if code is None:
                continue
            handle = getattr(proc, "_barry_log_handle", None)
            if handle:
                if code == 0:
                    handle.write(f"[{time.strftime('%F %T')}] line={name} exited code=0; completed, no restart\n")
                elif code == WINDOW_PAUSED_EXIT_CODE:
                    handle.write(f"[{time.strftime('%F %T')}] line={name} exited code={code}; window paused, wait for next active window\n")
                else:
                    handle.write(f"[{time.strftime('%F %T')}] line={name} exited code={code}; restart in 10s\n")
                handle.flush()
                handle.close()
            children.pop(name, None)
            if code == 0:
                completed.add(name)
                _log(f"{name} worker 正常结束（code=0），视为已达标/已停止，不再重启。")
                continue
            if code == WINDOW_PAUSED_EXIT_CODE:
                _log(f"{name} worker 到达时间窗外，暂停运行，等待下一次窗口打开。")
                continue
            if not _line_in_window(config):
                _log(f"{name} worker 退出（code={code}），但当前在时间窗外，暂不重启。")
                continue
            _log(f"{name} worker 退出（code={code}），10s 后拉起。")
            time.sleep(10)
            if stopping:
                break
            children[name] = _spawn_line(name, config)
            _log(f"已重启 {name} worker，pid={children[name].pid}。")
        _maybe_spawn_ready_lines("window-open")
        all_completed = bool(enabled_lines) and completed.issuperset(enabled_lines)
        any_running = any(proc.poll() is None for proc in children.values())
        if all_completed and not any_running:
            if ROLLOVER_RESET_ENABLED or TIME_WINDOW_ENABLED:
                if not waiting_for_rollover_logged:
                    _log("当前自然日所有已启用线路都已结束；因已开启跨 0 点自动清零，supervisor 保持待机直到日期切换。")
                    waiting_for_rollover_logged = True
                continue
            _log("所有已启用 worker 均已结束。")
            return 0

    _stop_children()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
