from __future__ import annotations

from typing import Any

from inbeidou_cli import get_publish_accounts, require_success


def sync_publish_accounts(*, language: str, country: str, tier: str, daily_post_limit: int) -> list[dict[str, Any]]:
    rows = require_success(get_publish_accounts(), "同步发布账号池")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        publish_account_id = str(row.get("id") or "")
        if not publish_account_id:
            continue
        normalized.append(
            {
                "agent_id": f"publish_account:{publish_account_id}",
                "owner_agent_id": str(row.get("agent_id") or ""),
                "publish_account_id": publish_account_id,
                "team_id": str(row.get("team_id") or ""),
                "platform": str(row.get("type") or ""),
                "language": str(language),
                "country": str(country or ""),
                "provider": "bundle_social",
                "tier": str(tier),
                "daily_post_limit": int(daily_post_limit),
                "status": "active" if int(row.get("status") or 0) == 0 else "inactive",
                "social_name": str(row.get("social_name") or ""),
                "social_account_id": str(row.get("social_account_id") or ""),
                "channel_id": str(row.get("channel_id") or ""),
                "notes": "synced from publish accounts api",
            }
        )
    return normalized

