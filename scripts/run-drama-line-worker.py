#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from flywheel.daily_loop_targets import get_pool_target_status, select_balanced_account_ids  # noqa: E402


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, str(default))).strip() or default)
    except Exception:
        return default


def _log(message: str) -> None:
    print(f"[{datetime.now().strftime('%F %T')}] {message}", flush=True)


def _read_log_tail_from_offset(log_path: Path, start_offset: int) -> str:
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(max(0, int(start_offset)))
            return handle.read()
    except Exception:
        return ""


def _is_realtime_no_material_error(stderr_text: str) -> bool:
    text = str(stderr_text or "")
    return any(
        marker in text
        for marker in (
            "实时榜线路当前没有可下载外部素材",
            "实时榜线路已拉到外部素材候选，但没有可直接进入剪辑的素材",
        )
    )


def _is_creative_list_no_material_error(stderr_text: str) -> bool:
    text = str(stderr_text or "")
    return any(
        marker in text
        for marker in (
            "创意列表线路当前没有匹配到可下载外部素材",
            "创意列表线路已匹配到候选素材，但没有可直接进入剪辑的外部视频",
        )
    )


def _write_material_unavailable_round_json(
    *,
    json_path: Path,
    line_name: str,
    round_name: str,
    requested_count: int,
    status: str,
    message: str,
) -> None:
    payload = {
        "status": str(status or "").strip() or "no_material",
        "mode": "continuous",
        "platform": "FACEBOOK",
        "line_name": line_name,
        "round_name": round_name,
        "requested_count": int(requested_count or 0),
        "message": str(message or "").strip() or "当前没有可用素材",
        "items": [],
        "publish_records": [],
        "report_zh": {
            "请求数量": int(requested_count or 0),
            "计划数量": int(requested_count or 0),
            "发布成功数": 0,
            "失败数": 0,
            "发布处理中数": 0,
        },
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_realtime_rank_line(line_name: str) -> bool:
    return str(line_name or "").strip().lower() in {"realtime", "realtime_day", "realtime_single"}


def _is_no_available_account_error(message: str) -> bool:
    text = str(message or "").strip()
    return "没有可用账号" in text or "可用账号不足" in text


def _runtime_paths(line_name: str) -> tuple[str, Path, Path, Path]:
    day = datetime.now().strftime("%Y-%m-%d")
    state_root = Path(os.getenv("BARRY_LOOP_STATE_ROOT", str(ROOT_DIR / "runtime" / "continuous-loop"))).expanduser()
    report_root = Path(os.getenv("BARRY_LOOP_REPORT_DIR", str(ROOT_DIR / "runtime" / "reports" / "test-summary"))).expanduser()
    run_dir = state_root / day / line_name
    log_path = run_dir / "worker.log"
    report_dir = report_root / day / line_name
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    return day, run_dir, log_path, report_dir


def _load_tracker_config() -> dict:
    path = ROOT_DIR / "conf" / "video_pipeline_tracker.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False}
    return payload if isinstance(payload, dict) else {"enabled": False}


def _tracker_enabled(config: dict) -> bool:
    return str(config.get("enabled") or "").strip().lower() in {"1", "true", "yes", "on"}


def _write_tracker_error(path: Path, *, stage: str, error: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": False,
                "stage": stage,
                "error": str(error or ""),
                "written_at": datetime.now().strftime("%F %T"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _json_file_has_payload(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return False
    if not text:
        return False
    try:
        payload = json.loads(text)
    except Exception:
        return False
    return isinstance(payload, dict) and bool(payload)


def _run_tracker_command(cmd: list[str], *, log_path: Path, stage: str, fallback_output: Path | None = None) -> bool:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[{datetime.now().strftime('%F %T')}] tracker {stage}: {' '.join(cmd)}\n")
        handle.flush()
        result = subprocess.run(cmd, cwd=str(ROOT_DIR), text=True, stdout=handle, stderr=handle, check=False)
    if result.returncode == 0:
        return True
    if fallback_output is not None and not fallback_output.exists():
        _write_tracker_error(fallback_output, stage=stage, error=f"tracker command failed rc={result.returncode}")
    _log(f"tracker {stage} 失败（rc={result.returncode}），发布主流程继续。")
    return False


def _prepare_tracker_artifacts(
    *,
    config: dict,
    line_name: str,
    label: str,
    artifact_dir: Path,
    log_path: Path,
) -> tuple[Path, Path, Path]:
    bundle_path = artifact_dir / "strategy-bundle.json"
    context_path = artifact_dir / "strategy-context.json"
    tasks_path = artifact_dir / "tasks.json"
    if not _tracker_enabled(config):
        return bundle_path, context_path, tasks_path

    artifact_dir.mkdir(parents=True, exist_ok=True)
    api_base = str(config.get("api_base") or "").strip()
    owner = str(config.get("owner") or "").strip()
    uid = str(config.get("uid") or "").strip()
    loop_name = str(config.get("loop_name") or "liuxinyu-ai-loop").strip()
    account_type = str(config.get("account_type") or "FACEBOOK").strip()
    min_accounts = str(int(config.get("min_accounts") or 0))
    execute = str(config.get("execute") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not api_base or not owner:
        _write_tracker_error(bundle_path, stage="prepare", error="missing api_base or owner in conf/video_pipeline_tracker.json")
        _write_tracker_error(context_path, stage="claim", error="missing api_base or owner in conf/video_pipeline_tracker.json")
        return bundle_path, context_path, tasks_path

    pull_cmd = [
        sys.executable,
        str(ROOT_DIR / "tools" / "video-pipeline-tracker" / "scripts" / "pull_dashboard_strategy.py"),
        "--api-base",
        api_base,
        "--owner",
        owner,
        "--uid",
        uid,
        "--loop-name",
        loop_name,
        "--account-type",
        account_type,
        "--min-accounts",
        min_accounts,
        "--output",
        str(bundle_path),
    ]
    if not _run_tracker_command(pull_cmd, log_path=log_path, stage="pull_strategy_bundle", fallback_output=bundle_path):
        _write_tracker_error(context_path, stage="claim_strategy", error="strategy bundle unavailable")
        return bundle_path, context_path, tasks_path

    claim_cmd = [
        sys.executable,
        str(ROOT_DIR / "tools" / "video-pipeline-tracker" / "scripts" / "claim_strategy_binding.py"),
        "--api-base",
        api_base,
        "--owner",
        owner,
        "--loop-name",
        loop_name,
        "--round-name",
        label,
        "--strategy-bundle",
        str(bundle_path),
        "--output",
        str(context_path),
    ]
    if execute:
        claim_cmd.append("--execute")
    _run_tracker_command(claim_cmd, log_path=log_path, stage="claim_strategy", fallback_output=context_path)
    return bundle_path, context_path, tasks_path


def _push_tracker_artifacts(
    *,
    config: dict,
    line_name: str,
    label: str,
    json_path: Path,
    context_path: Path,
    tasks_path: Path,
    log_path: Path,
) -> None:
    if not _tracker_enabled(config):
        return
    if not _json_file_has_payload(json_path):
        _write_tracker_error(tasks_path, stage="push_result", error="round json empty or not parseable; skip tracker push")
        _log(f"tracker push_round_result 跳过：{json_path.name} 为空或不可解析。")
        return
    api_base = str(config.get("api_base") or "").strip()
    owner = str(config.get("owner") or "").strip()
    uid = str(config.get("uid") or "").strip()
    loop_name = str(config.get("loop_name") or "liuxinyu-ai-loop").strip()
    execute = str(config.get("execute") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not api_base or not owner:
        _write_tracker_error(tasks_path, stage="push_result", error="missing api_base or owner in conf/video_pipeline_tracker.json")
        return
    cmd = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "push-loop-round-to-tracker.py"),
        "--round-json",
        str(json_path),
        "--strategy-context",
        str(context_path),
        "--owner",
        owner,
        "--uid",
        uid,
        "--loop-name",
        loop_name,
        "--round-name",
        label,
        "--line-name",
        line_name,
        "--api-base",
        api_base,
        "--output",
        str(tasks_path),
    ]
    if execute:
        cmd.append("--execute")
    _run_tracker_command(cmd, log_path=log_path, stage="push_round_result", fallback_output=tasks_path)


def _next_round_name(run_dir: Path) -> str:
    max_index = 0
    for path in run_dir.glob("round*.json"):
        stem = path.stem
        suffix = stem[5:]
        if suffix.isdigit():
            max_index = max(max_index, int(suffix))
    return f"round{max_index + 1}"


def _line_run_dir(line_name: str) -> Path:
    day = datetime.now().strftime("%Y-%m-%d")
    state_root = Path(os.getenv("BARRY_LOOP_STATE_ROOT", str(ROOT_DIR / "runtime" / "continuous-loop"))).expanduser()
    return state_root / day / line_name


def _requested_count(pool_name: str, run_dir: Path, *, platform: str, configured_count: int) -> tuple[int, dict]:
    account_success_target = _env_int("BARRY_LOOP_ACCOUNT_SUCCESS_TARGET", 10)
    status = get_pool_target_status(
        root_dir=ROOT_DIR,
        run_dir=run_dir,
        pool_name=pool_name,
        platform=platform,
        account_success_target=account_success_target,
    )
    eligible = int(status.get("eligible_pool_size") or 0)
    unmet_accounts = int(status.get("unmet_account_count") or 0)
    if account_success_target > 0:
        effective_eligible = max(0, unmet_accounts)
    else:
        effective_eligible = max(0, eligible)
    if effective_eligible <= 0:
        return 0, status
    if configured_count > 0:
        requested = min(configured_count, effective_eligible)
    else:
        requested = effective_eligible
    return max(0, requested), status


def _dependency_line_ready(*, line_name: str, pool_name: str, platform: str, account_success_target: int) -> tuple[bool, dict]:
    run_dir = _line_run_dir(line_name)
    status = get_pool_target_status(
        root_dir=ROOT_DIR,
        run_dir=run_dir,
        pool_name=pool_name,
        platform=platform,
        account_success_target=account_success_target,
    )
    unmet_accounts = int(status.get("unmet_account_count") or 0)
    remaining_deficit = int(status.get("remaining_success_deficit") or 0)
    return unmet_accounts <= 0 and remaining_deficit <= 0, status


def _write_summary(
    *,
    json_path: Path,
    summary_path: Path,
    round_name: str,
    label: str,
    started: str,
    requested_arg: int,
) -> dict:
    payload = {}
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
    payload_status = str(payload.get("status") or "").strip()
    payload_message = str(payload.get("message") or payload.get("error") or "").strip()
    requested = int(payload.get("requested_count") or report.get("请求数量") or requested_arg or 0)
    success = int(report.get("发布成功数") or 0)
    failed = int(report.get("失败数") or 0)
    processing = int(report.get("发布处理中数") or 0)
    planned = int(report.get("计划数量") or requested or requested_arg or 0)
    unsubmitted = max(planned - success - failed - processing, 0)
    status = "done" if payload else "error"
    status_label = "已完成"
    note = ""
    if payload_status and payload_status not in {"success", "ok", "done"}:
        if payload_status == "no_enough_playable_dramas":
            status = "blocked"
            status_label = "素材不足"
            requested = max(requested, requested_arg)
            planned = max(planned, requested_arg)
            unsubmitted = max(unsubmitted, requested_arg)
        elif payload_status == "no_realtime_material":
            status = "blocked"
            status_label = "等待素材"
            requested = max(requested, requested_arg)
            planned = max(planned, requested_arg)
            unsubmitted = max(unsubmitted, requested_arg)
        elif payload_status == "no_creative_list_material":
            status = "blocked"
            status_label = "素材未命中"
            requested = max(requested, requested_arg)
            planned = max(planned, requested_arg)
            unsubmitted = max(unsubmitted, requested_arg)
        else:
            status = "error"
            status_label = "异常结束"
        note = payload_message or payload_status
    elif not payload:
        status_label = "异常结束"
        note = "结果文件为空或不可解析"

    summary_path.write_text(
        "\n".join(
            [
                f"round={round_name}",
                f"label={label}",
                "scheduled_time=continuous",
                f"started_at={started}",
                f"status={status}",
                f"status_label={status_label}",
                f"requested_count={requested}",
                f"planned_count={planned}",
                f"success_count={success}",
                f"failed_count={failed}",
                f"processing_count={processing}",
                f"unsubmitted_count={unsubmitted}",
                f"report_file={str(((payload.get('test_report_files') or {}).get('markdown') or '')).strip()}",
                f"note={note}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "status": status,
        "requested": requested,
        "success": success,
        "failed": failed,
        "processing": processing,
        "unsubmitted": unsubmitted,
        "note": note,
    }


def main() -> int:
    line_name = str(os.getenv("BARRY_LOOP_LINE_NAME") or "").strip() or "ordinary"
    pool_name = str(os.getenv("BARRY_LOOP_ACCOUNT_POOL") or "").strip()
    if not pool_name:
        raise SystemExit("missing BARRY_LOOP_ACCOUNT_POOL")
    flywheel_config = str(os.getenv("BARRY_LOOP_FLYWHEEL_CONFIG") or "").strip()
    platform = str(os.getenv("BARRY_LOOP_PLATFORM") or "FACEBOOK").strip() or "FACEBOOK"
    configured_count = _env_int("BARRY_LOOP_COUNT", 0)
    account_success_target = _env_int("BARRY_LOOP_ACCOUNT_SUCCESS_TARGET", 10)
    idle_sleep = _env_int("BARRY_LOOP_LINE_IDLE_SLEEP_SECONDS", 300)
    cycle_sleep = _env_int("BARRY_LOOP_LINE_SLEEP_SECONDS", 60 if line_name == "realtime" else 60)
    error_sleep = _env_int("BARRY_LOOP_LINE_ERROR_SLEEP_SECONDS", 20)
    realtime_no_material_sleep = _env_int(
        "BARRY_LOOP_REALTIME_NO_MATERIAL_SLEEP_SECONDS",
        3600 if _is_realtime_rank_line(line_name) else 0,
    )
    creative_list_no_material_sleep = _env_int(
        "BARRY_LOOP_CREATIVE_LIST_NO_MATERIAL_SLEEP_SECONDS",
        3600 if str(line_name or "").strip().lower() in {"creative_list", "creative_list_day"} else 0,
    )
    creative_list_material_only = "1" if _truthy(os.getenv("BARRY_LOOP_CREATIVE_LIST_MATERIAL_ONLY", "0")) else "0"
    wait_for_line = str(os.getenv("BARRY_LOOP_WAIT_FOR_LINE") or "").strip().lower()
    wait_for_line_pool = str(os.getenv("BARRY_LOOP_WAIT_FOR_LINE_POOL") or "").strip()
    allow_reuse = _truthy(os.getenv("BARRY_LOOP_ALLOW_ACCOUNT_REUSE", "1"))
    realtime_enabled = "1" if _truthy(os.getenv("BARRY_REALTIME_RANK_ENABLED", "0")) else "0"
    realtime_material_only = "1" if _truthy(os.getenv("BARRY_LOOP_REALTIME_MATERIAL_ONLY", "0")) else "0"
    tracker_config = _load_tracker_config()

    while True:
        if wait_for_line and wait_for_line_pool:
            ready, dependency_status = _dependency_line_ready(
                line_name=wait_for_line,
                pool_name=wait_for_line_pool,
                platform=platform,
                account_success_target=account_success_target,
            )
            if not ready:
                _log(
                    f"{line_name} 等待上游 {wait_for_line}：账号池={wait_for_line_pool}，"
                    f"未达标账号={int(dependency_status.get('unmet_account_count') or 0)}，"
                    f"剩余缺口={int(dependency_status.get('remaining_success_deficit') or 0)}；{idle_sleep}s 后重试。"
                )
                time.sleep(max(5, idle_sleep))
                continue
        _, run_dir, log_path, report_dir = _runtime_paths(line_name)
        round_name = _next_round_name(run_dir)
        label = f"{line_name}-{round_name}"
        requested, status = _requested_count(
            pool_name,
            run_dir,
            platform=platform,
            configured_count=configured_count,
        )
        eligible_accounts = int(status.get("eligible_pool_size") or 0)
        unmet_accounts = int(status.get("unmet_account_count") or 0)
        remaining_deficit = int(status.get("remaining_success_deficit") or 0)
        if requested <= 0 or eligible_accounts <= 0:
            if unmet_accounts <= 0 and remaining_deficit <= 0:
                _log(
                    f"{line_name} 已达成账号目标并停止：账号池={pool_name}，账号日目标={account_success_target}，"
                    f"已达标账号={int(status.get('total_pool_size') or eligible_accounts or 0)}。"
                )
                return 0
            _log(
                f"{line_name} 空闲：账号池={pool_name}，账号日目标={account_success_target}，"
                f"未达标账号={unmet_accounts}，剩余缺口={remaining_deficit}；{idle_sleep}s 后继续检查。"
            )
            time.sleep(max(5, idle_sleep))
            continue

        try:
            selected = select_balanced_account_ids(
                root_dir=ROOT_DIR,
                run_dir=run_dir,
                pool_name=pool_name,
                platform=platform,
                requested_count=requested,
                account_success_target=account_success_target,
                allow_reuse=allow_reuse,
            )
        except Exception as exc:
            if _is_no_available_account_error(str(exc)):
                refreshed_status = get_pool_target_status(
                    root_dir=ROOT_DIR,
                    run_dir=run_dir,
                    pool_name=pool_name,
                    platform=platform,
                    account_success_target=account_success_target,
                )
                refreshed_unmet = int(refreshed_status.get("unmet_account_count") or 0)
                refreshed_deficit = int(refreshed_status.get("remaining_success_deficit") or 0)
                if refreshed_unmet <= 0 and refreshed_deficit <= 0:
                    _log(
                        f"{line_name} 已达成账号目标并停止：账号池={pool_name}，账号日目标={account_success_target}，"
                        f"可用账号已全部达标。"
                    )
                    return 0
            _log(f"{line_name} 选账号失败：{exc}；{error_sleep}s 后重试。")
            time.sleep(max(5, error_sleep))
            continue

        account_ids = [str(item).strip() for item in (selected.get("account_ids") or []) if str(item).strip()]
        if len(account_ids) < requested:
            _log(f"{line_name} 可用账号不足：需要 {requested} 个，实际 {len(account_ids)} 个；{error_sleep}s 后重试。")
            time.sleep(max(5, error_sleep))
            continue

        json_path = run_dir / f"{round_name}.json"
        summary_path = run_dir / f"{round_name}.summary"
        started = datetime.now().strftime("%F %T")
        line_report_dir = report_dir / round_name
        line_report_dir.mkdir(parents=True, exist_ok=True)
        tracker_dir = run_dir / round_name
        _bundle_path, context_path, tasks_path = _prepare_tracker_artifacts(
            config=tracker_config,
            line_name=line_name,
            label=label,
            artifact_dir=tracker_dir,
            log_path=log_path,
        )
        cmd = [
            "env",
            "BARRY_FEISHU_TEST_PUSH=0",
            f"BARRY_VIDEO_TEST_SUMMARY_DIR={line_report_dir}",
            f"BARRY_LOOP_LINE_NAME={line_name}",
            f"BARRY_LOOP_ROUND_LABEL={label}",
            "BARRY_LOOP_ROUND_SCHEDULED_TIME=continuous",
            f"BARRY_LOOP_ROUND_STARTED_AT={started}",
            f"BARRY_REALTIME_RANK_ENABLED={realtime_enabled}",
        ]
        if flywheel_config:
            cmd.append(f"FLYWHEEL_CONFIG={flywheel_config}")
        cmd.extend([
            "barry-video",
            "backend",
            "run-batch-drama",
            "--execute",
            "--count",
            str(requested),
            "--publish-platform",
            platform,
            "--json",
        ])
        if allow_reuse:
            cmd.append("--allow-account-reuse")
        for account_id in account_ids:
            cmd.extend(["--account-id", account_id])

        _log(
            f"{label} 开始：账号池={pool_name}，请求={requested}，未达标可用账号={int(selected.get('eligible_pool_size') or 0)}，"
            f"账号日目标={account_success_target}，"
            f"取数模式=按账号池动态，"
            f"配置={flywheel_config or '默认'}，"
            f"实时榜={'开启' if realtime_enabled == '1' else '关闭'}，"
            f"素材直驱={'开启' if realtime_material_only == '1' else '关闭'}，"
            f"创意列表直驱={'开启' if creative_list_material_only == '1' else '关闭'}，"
            f"官方切片={'FFmpeg' if line_name in {'fbhot_test', 'yourchannel'} else '默认'}。"
        )
        with log_path.open("a", encoding="utf-8") as log_handle, json_path.open("w", encoding="utf-8") as json_handle:
            log_handle.write(f"\n[{datetime.now().strftime('%F %T')}] $ {' '.join(cmd)}\n")
            log_handle.flush()
            log_offset = log_handle.tell()
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT_DIR),
                text=True,
                stdout=json_handle,
                stderr=log_handle,
                check=False,
            )
        log_text = _read_log_tail_from_offset(log_path, log_offset)
        realtime_no_material = (
            _is_realtime_rank_line(line_name)
            and realtime_no_material_sleep > 0
            and _is_realtime_no_material_error(log_text)
        )
        if realtime_no_material and not _json_file_has_payload(json_path):
            _write_material_unavailable_round_json(
                json_path=json_path,
                line_name=line_name,
                round_name=round_name,
                requested_count=requested,
                status="no_realtime_material",
                message="实时榜当前没有可下载外部素材；已等待下一小时重新拉取。",
            )
        creative_list_no_material = (
            str(line_name or "").strip().lower() in {"creative_list", "creative_list_day"}
            and _is_creative_list_no_material_error(log_text)
        )
        if creative_list_no_material and not _json_file_has_payload(json_path):
            _write_material_unavailable_round_json(
                json_path=json_path,
                line_name=line_name,
                round_name=round_name,
                requested_count=requested,
                status="no_creative_list_material",
                message="创意列表当前未命中可下载外部素材；整轮剧场已完成扫描，不回退到官方选剧逻辑。",
            )
        if proc.returncode != 0:
            _log(f"{label} 命令返回非零（rc={proc.returncode}），继续按结果文件汇总。")
        metrics = _write_summary(
            json_path=json_path,
            summary_path=summary_path,
            round_name=round_name,
            label=label,
            started=started,
            requested_arg=requested,
        )
        _push_tracker_artifacts(
            config=tracker_config,
            line_name=line_name,
            label=label,
            json_path=json_path,
            context_path=context_path,
            tasks_path=tasks_path,
            log_path=log_path,
        )
        if realtime_no_material:
            _log(
                f"{label} 未拿到可用实时榜素材：等待 {realtime_no_material_sleep}s 后再拉取下一轮，不重置账号达标标签。"
            )
            time.sleep(max(5, realtime_no_material_sleep))
            continue
        if creative_list_no_material and creative_list_no_material_sleep > 0:
            _log(
                f"{label} 创意列表整轮剧场已扫空：等待 {creative_list_no_material_sleep}s 后再开启下一轮扫描。"
            )
            time.sleep(max(5, creative_list_no_material_sleep))
            continue
        _log(
            f"{label} 完成：成功 {metrics['success']}，失败 {metrics['failed']}，处理中 {metrics['processing']}，未提交 {metrics['unsubmitted']}。"
        )
        time.sleep(max(5, cycle_sleep))


if __name__ == "__main__":
    raise SystemExit(main())
