from __future__ import annotations

from typing import Any

from .constraints import account_is_active, account_matches_language, account_matches_platform


def _tier_fit(account_tier: str, drama_tier: str) -> float:
    matrix = {
        "established": {"A": 1.0, "B": 0.8, "C": 0.5, "D": 0.3},
        "warming": {"A": 0.7, "B": 1.0, "C": 0.8, "D": 0.5},
        "new": {"A": 0.3, "B": 0.5, "C": 1.0, "D": 0.8},
    }
    return matrix.get(account_tier or "new", {}).get(drama_tier, 0.5)


def match_accounts(
    picks: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    *,
    target_platforms: list[str] | None = None,
    target_account_ids: list[str] | None = None,
) -> dict[str, Any]:
    normalized_targets = {str(value).upper() for value in (target_platforms or []) if str(value).strip()}
    normalized_accounts = {str(value).strip() for value in (target_account_ids or []) if str(value).strip()}
    available_accounts = [
        dict(account)
        for account in accounts
        if account_is_active(account) and account_matches_platform(account, normalized_targets)
        and (
            not normalized_accounts
            or str(account.get("publish_account_id") or "").strip() in normalized_accounts
            or str(account.get("id") or "").strip() in normalized_accounts
            or str(account.get("agent_id") or "").strip() in normalized_accounts
        )
    ]
    remaining = {str(account["id"]): int(account.get("daily_post_limit") or 0) for account in available_accounts}
    publish_plans: list[dict[str, Any]] = []
    underfilled: list[dict[str, Any]] = []

    sorted_picks = sorted(picks, key=lambda item: (item.get("tier"), -(item.get("final_score") or 0.0)))
    for pick in sorted_picks:
        assigned = 0
        ranked_accounts = sorted(
            [
                account
                for account in available_accounts
                if account_matches_language(account, pick) and remaining.get(str(account["id"]), 0) > 0
            ],
            key=lambda account: _tier_fit(str(account.get("tier") or "new"), str(pick.get("tier") or "D")),
            reverse=True,
        )
        for account in ranked_accounts:
            if assigned >= int(pick.get("slot_count") or 0):
                break
            publish_plans.append(
                {
                    "account_id": account.get("publish_account_id") or account["id"],
                    "agent_id": account.get("owner_agent_id") or account["agent_id"],
                    "team_id": account.get("team_id") or "",
                    "serial_id": pick["serial_id"],
                    "title": pick.get("title") or "",
                    "platform": account["platform"],
                    "caption": "",
                    "status": "pending",
                    "video_asset_id": None,
                    "scheduled_at": None,
                }
            )
            remaining[str(account["id"])] -= 1
            assigned += 1
        if assigned < int(pick.get("slot_count") or 0):
            underfilled.append(
                {
                    "serial_id": pick["serial_id"],
                    "title": pick.get("title"),
                    "tier": pick.get("tier"),
                    "requested_slots": int(pick.get("slot_count") or 0),
                    "assigned_slots": assigned,
                }
            )

    return {
        "publish_plans": publish_plans,
        "underfilled": underfilled,
        "accounts_available": len(available_accounts),
        "target_platforms": sorted(normalized_targets),
        "target_account_ids": sorted(normalized_accounts),
    }
