from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from time import time

from inbeidou_cli import get_publish_accounts, require_success

UNSUPPORTED_REEL_PATTERNS = (
    "账号不能发布reel视频",
    "账号不能发布 reel 视频",
    "cannot publish reel",
    "can't publish reel",
    "not allowed to publish reel",
)

SUCCESS_TARGET_RESET_FILE = ".success_target_reset.json"


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


def _loop_success_stats(run_dir: Path) -> tuple[dict[str, int], set[str]]:
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
    success_counts, unsupported_accounts = _loop_success_stats(run)

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
    success_counts, unsupported_accounts = _loop_success_stats(run)

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
