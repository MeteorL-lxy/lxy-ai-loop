#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from inbeidou_cli import get_publish_accounts, require_success  # noqa: E402

ACCOUNT_POOLS_PATH = PROJECT_ROOT / "conf" / "account_pools.json"
RESERVE_POOL = "facebook_drama_reserve_pool"
MANAGED_POOLS = (
    "facebook_drama_realtime_pool",
    "facebook_drama_realtime_single_pool",
    "facebook_drama_realtime_day_pool",
    "facebook_drama_creative_list_pool",
    "facebook_drama_creative_list_day_pool",
    "facebook_drama_ordinary_pool",
    "facebook_drama_fbhot_test_pool",
    "facebook_drama_yourchannel_pool",
    "facebook_drama_recent_order_pool",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _load_pools() -> dict[str, Any]:
    payload = json.loads(ACCOUNT_POOLS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("account_pools.json 格式不是对象")
    return payload


def _save_pools(payload: dict[str, Any]) -> None:
    temp_path = ACCOUNT_POOLS_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(ACCOUNT_POOLS_PATH)


def _normalize_ids(values: Any) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for item in values or []:
        value = _text(item)
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _ensure_pool(payload: dict[str, Any], pool_name: str) -> dict[str, Any]:
    raw = payload.get(pool_name)
    if not isinstance(raw, dict):
        raw = {"platform": "FACEBOOK", "description": "", "account_ids": []}
        payload[pool_name] = raw
    raw["account_ids"] = _normalize_ids(raw.get("account_ids"))
    return raw


def _fetch_active_facebook_accounts() -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    rows = require_success(get_publish_accounts(), "拉取发布账号列表")
    active_map: dict[str, dict[str, Any]] = {}
    active_rows: list[dict[str, Any]] = []
    for row in rows:
        if _text(row.get("type")).upper() != "FACEBOOK":
            continue
        if int(row.get("status") or 0) != 0:
            continue
        account_id = _text(row.get("id"))
        if not account_id:
            continue
        normalized = {
            "account_id": account_id,
            "social_name": _text(row.get("social_name")),
            "social_profile_url": _text(row.get("social_profile_url")),
            "channel_id": _text(row.get("channel_id")),
            "team_id": _text(row.get("team_id")),
        }
        active_map[account_id] = normalized
        active_rows.append(normalized)
    return active_map, active_rows


def reconcile_pools(*, write: bool) -> dict[str, Any]:
    payload = _load_pools()
    active_accounts, active_rows = _fetch_active_facebook_accounts()
    active_ids = set(active_accounts.keys())

    summary: dict[str, Any] = {
        "checked_at": datetime.now().strftime("%F %T"),
        "write": bool(write),
        "active_facebook_accounts": len(active_rows),
        "new_accounts_added_to_reserve": [],
        "removed_inactive_accounts": {},
        "pool_refills": {},
        "unfilled_gaps": {},
        "reserve_before": 0,
        "reserve_after": 0,
        "changed": False,
    }

    # 1) prune inactive / missing accounts from all facebook pools
    for pool_name, raw in list(payload.items()):
        if not isinstance(raw, dict):
            continue
        if _text(raw.get("platform")).upper() != "FACEBOOK":
            continue
        account_ids = _normalize_ids(raw.get("account_ids"))
        kept = [account_id for account_id in account_ids if account_id in active_ids]
        removed = [account_id for account_id in account_ids if account_id not in active_ids]
        raw["account_ids"] = kept
        if removed:
            summary["removed_inactive_accounts"][pool_name] = [
                {
                    "account_id": account_id,
                    "reason": "账号已不在当前可用的 Facebook 发布账号列表里",
                }
                for account_id in removed
            ]

    reserve_pool = _ensure_pool(payload, RESERVE_POOL)
    summary["reserve_before"] = len(reserve_pool["account_ids"])

    # 2) add new active accounts into reserve when not assigned anywhere
    assigned_ids: set[str] = set()
    for raw in payload.values():
        if not isinstance(raw, dict):
            continue
        assigned_ids.update(_normalize_ids(raw.get("account_ids")))

    for account in active_rows:
        account_id = account["account_id"]
        if account_id in assigned_ids:
            continue
        reserve_pool["account_ids"].append(account_id)
        assigned_ids.add(account_id)
        summary["new_accounts_added_to_reserve"].append(account)

    # 3) refill managed pools from reserve according to target_count
    reserve_ids = _normalize_ids(reserve_pool.get("account_ids"))
    reserve_pool["account_ids"] = reserve_ids
    for pool_name in MANAGED_POOLS:
        pool = _ensure_pool(payload, pool_name)
        target_count = int(pool.get("target_count") or 0)
        if target_count <= 0:
            continue
        pool_ids = _normalize_ids(pool.get("account_ids"))
        pool["account_ids"] = pool_ids
        gap = target_count - len(pool_ids)
        if gap <= 0:
            continue
        moved: list[dict[str, Any]] = []
        while gap > 0 and reserve_ids:
            account_id = reserve_ids.pop(0)
            if account_id in pool_ids:
                continue
            pool_ids.append(account_id)
            account = active_accounts.get(account_id, {"account_id": account_id, "social_name": "", "social_profile_url": ""})
            moved.append(account)
            gap -= 1
        if moved:
            summary["pool_refills"][pool_name] = {
                "target_count": target_count,
                "filled_count": len(moved),
                "accounts": moved,
            }
        if gap > 0:
            summary["unfilled_gaps"][pool_name] = {
                "target_count": target_count,
                "current_count": len(pool_ids),
                "missing_count": gap,
            }
        pool["account_ids"] = pool_ids

    reserve_pool["account_ids"] = reserve_ids
    summary["reserve_after"] = len(reserve_ids)
    summary["changed"] = bool(
        summary["new_accounts_added_to_reserve"]
        or summary["removed_inactive_accounts"]
        or summary["pool_refills"]
    )

    if write and summary["changed"]:
        _save_pools(payload)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="每天对齐发布账号与账号池，并自动补充备用池/补齐目标池缺口")
    parser.add_argument("--write", action="store_true", help="真实写回 conf/account_pools.json")
    args = parser.parse_args()
    result = reconcile_pools(write=bool(args.write))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
