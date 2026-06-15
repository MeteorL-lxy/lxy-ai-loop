from __future__ import annotations

import fcntl
import hashlib
import json
from contextlib import contextmanager
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from time import time
from typing import Any

from inbeidou_cli import get_publish_accounts, require_success

UNSUPPORTED_REEL_PATTERNS = (
    "账号不能发布reel视频",
    "账号不能发布 reel 视频",
    "cannot publish reel",
    "can't publish reel",
    "not allowed to publish reel",
)

SUCCESS_TARGET_RESET_FILE = ".success_target_reset.json"
REEL_BLOCK_POOL_NAME = "facebook_drama_reel_block_pool"
REEL_BLOCK_THRESHOLD = 5
REEL_BLOCK_STATE_DIR = "runtime/account-flags"
REEL_BLOCK_STATE_FILE = "reel_publish_block_state.json"
REEL_BLOCK_LOCK_FILE = "reel_publish_block_state.lock"
REEL_BLOCK_PROCESSED_EVENT_LIMIT = 20000
REEL_BLOCK_HISTORY_LIMIT = 30
REEL_BLOCK_EXCLUDED_MOVE_POOLS = {REEL_BLOCK_POOL_NAME}


def _is_unsupported_reel_reason(message: str) -> bool:
    normalized = str(message or "").strip().lower()
    return bool(normalized) and any(pattern.lower() in normalized for pattern in UNSUPPORTED_REEL_PATTERNS)


def _load_account_pool_ids(root_dir: Path, pool_name: str) -> list[str]:
    config_path = root_dir / "conf" / "account_pools.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    pool = data.get(pool_name) if isinstance(data, dict) else None
    if not isinstance(pool, dict):
        raise RuntimeError(f"未找到账号池: {pool_name}")
    return [str(item).strip() for item in (pool.get("account_ids") or []) if str(item).strip()]


def _load_account_pools_config(root_dir: Path) -> dict[str, Any]:
    config_path = root_dir / "conf" / "account_pools.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _save_account_pools_config(root_dir: Path, payload: dict[str, Any]) -> None:
    _atomic_write_json(root_dir / "conf" / "account_pools.json", payload)


def _reel_block_state_root(root_dir: Path) -> Path:
    return root_dir / REEL_BLOCK_STATE_DIR


def _reel_block_state_path(root_dir: Path) -> Path:
    return _reel_block_state_root(root_dir) / REEL_BLOCK_STATE_FILE


def _reel_block_lock_path(root_dir: Path) -> Path:
    return _reel_block_state_root(root_dir) / REEL_BLOCK_LOCK_FILE


@contextmanager
def _reel_block_lock(root_dir: Path):
    lock_path = _reel_block_lock_path(root_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_reel_block_state(root_dir: Path) -> dict[str, Any]:
    path = _reel_block_state_path(root_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    accounts = payload.get("accounts")
    processed = payload.get("processed_event_ids")
    payload["accounts"] = accounts if isinstance(accounts, dict) else {}
    payload["processed_event_ids"] = processed if isinstance(processed, list) else []
    payload["updated_at"] = str(payload.get("updated_at") or "")
    return payload


def _save_reel_block_state(root_dir: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = datetime.now().strftime("%F %T")
    _atomic_write_json(_reel_block_state_path(root_dir), payload)


def _ensure_reel_block_pool(pools: dict[str, Any]) -> dict[str, Any]:
    if REEL_BLOCK_POOL_NAME not in pools or not isinstance(pools.get(REEL_BLOCK_POOL_NAME), dict):
        pools[REEL_BLOCK_POOL_NAME] = {
            "platform": "FACEBOOK",
            "description": "Temporary pool for accounts that repeatedly fail with 'cannot publish reel'. Use reel_publish_block_state to inspect which line they were moved from.",
            "account_ids": [],
        }
    pool = pools[REEL_BLOCK_POOL_NAME]
    account_ids = pool.get("account_ids")
    pool["account_ids"] = account_ids if isinstance(account_ids, list) else []
    return pool


def _reel_event_id(*, run_dir: Path, round_name: str, item_index: int, account_id: str, outcome: str, reason: str) -> str:
    raw = "::".join(
        [
            str(run_dir),
            str(round_name or ""),
            str(item_index or 0),
            str(account_id or ""),
            str(outcome or ""),
            str(reason or ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _append_reel_history(account_state: dict[str, Any], entry: dict[str, Any]) -> None:
    history = account_state.get("history")
    if not isinstance(history, list):
        history = []
    history.append(entry)
    account_state["history"] = history[-REEL_BLOCK_HISTORY_LIMIT:]


def _move_account_to_reel_block_pool(
    *,
    root_dir: Path,
    pools: dict[str, Any],
    account_id: str,
    line_name: str,
    source_pool_name: str,
    account_state: dict[str, Any],
) -> bool:
    changed = False
    target_pool = _ensure_reel_block_pool(pools)
    target_ids = [str(item).strip() for item in (target_pool.get("account_ids") or []) if str(item).strip()]
    if account_id not in target_ids:
        target_ids.append(account_id)
        target_pool["account_ids"] = target_ids
        changed = True

    for pool_name, pool in pools.items():
        if pool_name in REEL_BLOCK_EXCLUDED_MOVE_POOLS or not isinstance(pool, dict):
            continue
        if not str(pool_name).startswith("facebook_drama_"):
            continue
        pool_ids = [str(item).strip() for item in (pool.get("account_ids") or []) if str(item).strip()]
        if account_id in pool_ids:
            pool["account_ids"] = [item for item in pool_ids if item != account_id]
            changed = True

    account_state["moved_to_pool"] = REEL_BLOCK_POOL_NAME
    account_state["moved_at"] = datetime.now().strftime("%F %T")
    account_state["moved_from_line"] = str(line_name or "")
    account_state["moved_from_pool"] = str(source_pool_name or "")
    account_state["moved_due_to_reel_block_streak"] = int(account_state.get("current_reel_block_streak") or 0)
    _append_reel_history(
        account_state,
        {
            "action": "moved_to_reel_block_pool",
            "line_name": str(line_name or ""),
            "source_pool_name": str(source_pool_name or ""),
            "at": datetime.now().strftime("%F %T"),
            "streak": int(account_state.get("current_reel_block_streak") or 0),
        },
    )
    if changed:
        _save_account_pools_config(root_dir, pools)
    return changed


def _apply_reel_block_tracking(
    *,
    root_dir: Path,
    run_dir: Path,
    pool_name: str,
    round_path: Path,
    item_rows: list[dict[str, Any]],
    detail_by_index: dict[int, dict[str, Any]],
) -> set[str]:
    unsupported_accounts: set[str] = set()
    line_name = str(run_dir.name or "").strip()
    with _reel_block_lock(root_dir):
        state = _load_reel_block_state(root_dir)
        pools = _load_account_pools_config(root_dir)
        _ensure_reel_block_pool(pools)
        accounts = state.get("accounts")
        processed_ids = state.get("processed_event_ids")
        processed_set = {str(item).strip() for item in processed_ids if str(item).strip()}
        processed_list = [str(item).strip() for item in processed_ids if str(item).strip()]
        state_changed = False
        pools_changed = False

        for item in item_rows:
            item = dict(item)
            index = int(item.get("index") or 0)
            account = item.get("account") if isinstance(item.get("account"), dict) else {}
            account_id = str(account.get("account_id") or "").strip()
            if not account_id:
                continue
            detail = detail_by_index.get(index, {})
            outcome = str(detail.get("发布情况") or "").strip()
            reason = str(detail.get("失败原因") or detail.get("错误") or "").strip()
            if not outcome and not reason:
                continue

            event_id = _reel_event_id(
                run_dir=run_dir,
                round_name=str(round_path.stem or ""),
                item_index=index,
                account_id=account_id,
                outcome=outcome,
                reason=reason,
            )
            if event_id in processed_set:
                if _is_unsupported_reel_reason(reason):
                    unsupported_accounts.add(account_id)
                continue

            processed_set.add(event_id)
            processed_list.append(event_id)
            processed_list = processed_list[-REEL_BLOCK_PROCESSED_EVENT_LIMIT:]
            account_state = accounts.get(account_id)
            if not isinstance(account_state, dict):
                account_state = {}
                accounts[account_id] = account_state

            if _is_unsupported_reel_reason(reason):
                unsupported_accounts.add(account_id)
                account_state["current_reel_block_streak"] = int(account_state.get("current_reel_block_streak") or 0) + 1
                account_state["total_reel_block_hits"] = int(account_state.get("total_reel_block_hits") or 0) + 1
                account_state["last_reel_block_reason"] = reason
                account_state["last_reel_block_line"] = line_name
                account_state["last_reel_block_round"] = str(round_path.stem or "")
                account_state["last_reel_block_at"] = datetime.now().strftime("%F %T")
                _append_reel_history(
                    account_state,
                    {
                        "action": "reel_block_hit",
                        "line_name": line_name,
                        "source_pool_name": str(pool_name or ""),
                        "round_name": str(round_path.stem or ""),
                        "reason": reason,
                        "at": datetime.now().strftime("%F %T"),
                        "streak": int(account_state.get("current_reel_block_streak") or 0),
                    },
                )
                if int(account_state.get("current_reel_block_streak") or 0) >= REEL_BLOCK_THRESHOLD:
                    pools_changed = (
                        _move_account_to_reel_block_pool(
                            root_dir=root_dir,
                            pools=pools,
                            account_id=account_id,
                            line_name=line_name,
                            source_pool_name=pool_name,
                            account_state=account_state,
                        )
                        or pools_changed
                    )
                state_changed = True
                continue

            if outcome:
                previous_streak = int(account_state.get("current_reel_block_streak") or 0)
                account_state["current_reel_block_streak"] = 0
                account_state["last_non_reel_outcome"] = outcome
                account_state["last_non_reel_reason"] = reason
                account_state["last_non_reel_line"] = line_name
                account_state["last_non_reel_round"] = str(round_path.stem or "")
                account_state["last_non_reel_at"] = datetime.now().strftime("%F %T")
                if previous_streak > 0:
                    _append_reel_history(
                        account_state,
                        {
                            "action": "reel_block_streak_reset",
                            "line_name": line_name,
                            "source_pool_name": str(pool_name or ""),
                            "round_name": str(round_path.stem or ""),
                            "outcome": outcome,
                            "reason": reason,
                            "at": datetime.now().strftime("%F %T"),
                            "previous_streak": previous_streak,
                        },
                    )
                state_changed = True

        if state_changed:
            state["processed_event_ids"] = processed_list
            _save_reel_block_state(root_dir, state)
        elif pools_changed:
            _save_reel_block_state(root_dir, state)

    return unsupported_accounts


def _load_success_target_reset_epoch(run_dir: Path) -> float:
    reset_path = run_dir / SUCCESS_TARGET_RESET_FILE
    try:
        payload = json.loads(reset_path.read_text(encoding="utf-8"))
    except Exception:
        return 0.0
    try:
        return float(payload.get("reset_epoch") or 0.0)
    except Exception:
        return 0.0


def reset_success_target_window(run_dir: str | Path) -> dict[str, object]:
    run = Path(run_dir).resolve()
    run.mkdir(parents=True, exist_ok=True)
    reset_epoch = time()
    reset_payload = {
        "reset_epoch": reset_epoch,
        "reset_at": datetime.fromtimestamp(reset_epoch).strftime("%F %T"),
    }
    reset_path = run / SUCCESS_TARGET_RESET_FILE
    try:
        previous = json.loads(reset_path.read_text(encoding="utf-8"))
    except Exception:
        previous = {}
    generation = int(previous.get("generation") or 0) + 1
    reset_payload["generation"] = generation
    reset_path.write_text(json.dumps(reset_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return reset_payload


def _loop_success_stats(root_dir: Path, run_dir: Path, pool_name: str) -> tuple[dict[str, int], set[str]]:
    success_counts: dict[str, int] = defaultdict(int)
    unsupported_accounts: set[str] = set()
    reset_epoch = _load_success_target_reset_epoch(run_dir)

    for path in sorted(run_dir.glob("round*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        item_rows = payload.get("items") if isinstance(payload.get("items"), list) else []
        report = payload.get("report_zh") if isinstance(payload.get("report_zh"), dict) else {}
        detail_rows = report.get("任务明细") if isinstance(report.get("任务明细"), list) else []
        detail_by_index = {
            int(row.get("序号") or 0): dict(row)
            for row in detail_rows
            if int(row.get("序号") or 0) > 0
        }
        unsupported_accounts.update(
            _apply_reel_block_tracking(
                root_dir=root_dir,
                run_dir=run_dir,
                pool_name=pool_name,
                round_path=path,
                item_rows=item_rows,
                detail_by_index=detail_by_index,
            )
        )
        for item in item_rows:
            item = dict(item)
            index = int(item.get("index") or 0)
            account = item.get("account") if isinstance(item.get("account"), dict) else {}
            account_id = str(account.get("account_id") or "").strip()
            if not account_id:
                continue
            detail = detail_by_index.get(index, {})
            outcome = str(detail.get("发布情况") or "").strip()
            reason = str(detail.get("失败原因") or detail.get("错误") or "").strip()
            if outcome == "发布成功" and path.stat().st_mtime >= reset_epoch:
                success_counts[account_id] += 1
            if _is_unsupported_reel_reason(reason):
                unsupported_accounts.add(account_id)

    return dict(success_counts), unsupported_accounts


def select_balanced_account_ids(
    *,
    root_dir: str | Path,
    run_dir: str | Path,
    pool_name: str,
    platform: str,
    requested_count: int,
    account_success_target: int = 0,
    allow_reuse: bool = False,
) -> dict[str, object]:
    root = Path(root_dir).resolve()
    run = Path(run_dir).resolve()
    pool_ids = set(_load_account_pool_ids(root, pool_name))
    success_counts, unsupported_accounts = _loop_success_stats(root, run, pool_name)

    accounts = require_success(get_publish_accounts(), "获取发布账号列表")
    active_pool_accounts = [
        {
            "account_id": str(account.get("id") or "").strip(),
            "team_id": str(account.get("team_id") or "").strip(),
            "name": str(account.get("social_name") or "").strip() or f"{platform} 账号",
        }
        for account in accounts
        if str(account.get("id") or "").strip() in pool_ids
        and str(account.get("type") or "").upper() == str(platform or "").upper()
        and str(account.get("team_id") or "").strip()
        and str(account.get("status") or "0") == "0"
    ]
    per_account_target = max(int(account_success_target or 0), 0)
    eligible_accounts = [
        dict(account)
        for account in active_pool_accounts
        if str(account.get("account_id") or "") not in unsupported_accounts
        and (
            per_account_target <= 0
            or int(success_counts.get(str(account.get("account_id") or ""), 0)) < per_account_target
        )
    ]
    if not eligible_accounts:
        raise RuntimeError(f"账号池 {pool_name} 没有可用账号")

    buckets: dict[int, list[dict[str, str]]] = defaultdict(list)
    for account in eligible_accounts:
        buckets[int(success_counts.get(str(account.get("account_id") or ""), 0))].append(account)

    ordered: list[dict[str, str]] = []
    for success_count in sorted(buckets):
        group = list(buckets[success_count])
        random.shuffle(group)
        ordered.extend(group)

    selected = ordered[:requested_count]
    if requested_count > len(selected) and allow_reuse and ordered:
        index = 0
        while len(selected) < requested_count:
            selected.append(dict(ordered[index % len(ordered)]))
            index += 1

    if len(selected) < requested_count:
        raise RuntimeError(
            f"账号池 {pool_name} 可用账号不足: 需要 {requested_count} 个，当前仅 {len(selected)} 个可用账号"
        )

    return {
        "account_ids": [str(account.get("account_id") or "") for account in selected],
        "accounts": selected,
        "active_pool_size": len(active_pool_accounts),
        "eligible_pool_size": len(eligible_accounts),
        "unsupported_account_ids": sorted(unsupported_accounts),
        "success_counts": {
            str(account.get("account_id") or ""): int(success_counts.get(str(account.get("account_id") or ""), 0))
            for account in eligible_accounts
        },
    }


def get_pool_target_status(
    *,
    root_dir: str | Path,
    run_dir: str | Path,
    pool_name: str,
    platform: str,
    account_success_target: int,
) -> dict[str, object]:
    root = Path(root_dir).resolve()
    run = Path(run_dir).resolve()
    pool_ids = set(_load_account_pool_ids(root, pool_name))
    success_counts, unsupported_accounts = _loop_success_stats(root, run, pool_name)

    accounts = require_success(get_publish_accounts(), "获取发布账号列表")
    active_pool_accounts = [
        {
            "account_id": str(account.get("id") or "").strip(),
            "team_id": str(account.get("team_id") or "").strip(),
            "name": str(account.get("social_name") or "").strip() or f"{platform} 账号",
        }
        for account in accounts
        if str(account.get("id") or "").strip() in pool_ids
        and str(account.get("type") or "").upper() == str(platform or "").upper()
        and str(account.get("team_id") or "").strip()
        and str(account.get("status") or "0") == "0"
    ]
    eligible_accounts = [
        dict(account)
        for account in active_pool_accounts
        if str(account.get("account_id") or "") not in unsupported_accounts
    ]

    per_account_target = max(int(account_success_target or 0), 0)
    eligible_ids = [str(account.get("account_id") or "") for account in eligible_accounts]
    eligible_success_counts = {account_id: int(success_counts.get(account_id, 0)) for account_id in eligible_ids}
    remaining_deficits = {
        account_id: max(per_account_target - eligible_success_counts.get(account_id, 0), 0)
        for account_id in eligible_ids
    }
    unmet_account_ids = [account_id for account_id, deficit in remaining_deficits.items() if deficit > 0]

    success_values = list(eligible_success_counts.values())
    return {
        "pool_name": pool_name,
        "platform": platform,
        "per_account_target": per_account_target,
        "active_pool_size": len(active_pool_accounts),
        "eligible_pool_size": len(eligible_accounts),
        "unsupported_account_ids": sorted(unsupported_accounts),
        "success_counts": eligible_success_counts,
        "target_total_success": len(eligible_accounts) * per_account_target,
        "current_total_success": sum(success_values),
        "min_success_count": min(success_values) if success_values else 0,
        "max_success_count": max(success_values) if success_values else 0,
        "remaining_success_deficit": sum(remaining_deficits.values()),
        "unmet_account_ids": unmet_account_ids,
        "unmet_account_count": len(unmet_account_ids),
    }
