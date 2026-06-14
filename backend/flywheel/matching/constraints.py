from __future__ import annotations

from typing import Any


def account_matches_language(account: dict[str, Any], pick: dict[str, Any]) -> bool:
    account_language = str(account.get("language") or "").strip()
    pick_language = str(pick.get("language") or "").strip()
    return not account_language or not pick_language or account_language == pick_language


def account_is_active(account: dict[str, Any]) -> bool:
    return str(account.get("status") or "active") == "active"


def account_matches_platform(account: dict[str, Any], target_platforms: set[str] | None) -> bool:
    if not target_platforms:
        return True
    return str(account.get("platform") or "").upper() in target_platforms
