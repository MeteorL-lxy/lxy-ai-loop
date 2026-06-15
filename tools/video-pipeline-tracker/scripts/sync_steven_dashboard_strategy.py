#!/usr/bin/env python3
"""
Export dashboard account/strategy records into Steven-jiao loop config files.

This keeps execution conservative:
  - account pool and A/B split are execution inputs
  - strategy tables are exported as metadata snapshots first
  - runtime strategy env only points to the snapshot, so unsupported rules do not
    silently change publish behavior
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OWNER = "焦千为"
DEFAULT_UID = "2265845568"
DEFAULT_API_BASE = "http://127.0.0.1:8770"


def fetch_table(api_base: str, table: str, limit: int = 100000) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"limit": limit})
    url = f"{api_base.rstrip('/')}/api/table/{urllib.parse.quote(table)}?{query}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        payload = json.load(resp)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError(f"{table} did not return rows")
    return [row for row in rows if isinstance(row, dict)]


def nonempty(value: Any) -> str:
    return str(value or "").strip()


def active_owner_accounts(rows: list[dict[str, Any]], owner: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    accounts: list[dict[str, Any]] = []
    for row in rows:
        if nonempty(row.get("owner")) != owner:
            continue
        if nonempty(row.get("account_type")).upper() != "FACEBOOK":
            continue
        if nonempty(row.get("deleted_at")):
            continue
        team_id = nonempty(row.get("team_id"))
        if not team_id or team_id in seen:
            continue
        seen.add(team_id)
        status = nonempty(row.get("status"))
        failure_count = row.get("failure_count_30")
        try:
            failure_count_int = int(failure_count or 0)
        except (TypeError, ValueError):
            failure_count_int = 0
        accounts.append(
            {
                "team_id": team_id,
                "social_account_id": nonempty(row.get("social_account_id")),
                "social_name": nonempty(row.get("social_name")) or "Facebook 账号",
                "channel_id": nonempty(row.get("channel_id")),
                "allocated_at": nonempty(row.get("allocated_at")),
                "status": status,
                "failure_count_30": failure_count_int,
                "source_claim_id": row.get("claim_id"),
            }
        )
    return accounts


def split_ab(accounts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Stable even/odd split preserves source order while keeping A/B balanced.
    group_a = [account for index, account in enumerate(accounts) if index % 2 == 0]
    group_b = [account for index, account in enumerate(accounts) if index % 2 == 1]
    return group_a, group_b


def load_existing_team_languages(loop_root: Path) -> dict[str, Any]:
    path = loop_root / "config" / "fb-shortdrama-team-languages.json"
    if not path.exists():
        return {"default_language": "2", "fallback_language": "2", "team_languages": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"default_language": "2", "fallback_language": "2", "team_languages": {}}
    if not isinstance(data, dict):
        return {"default_language": "2", "fallback_language": "2", "team_languages": {}}
    data.setdefault("default_language", "2")
    data.setdefault("fallback_language", "2")
    if not isinstance(data.get("team_languages"), dict):
        data["team_languages"] = {}
    return data


def write_team_ids(path: Path, accounts: list[dict[str, Any]]) -> None:
    lines = [account["team_id"] for account in accounts if account.get("team_id")]
    path.write_text("\n".join(lines).rstrip() + ("\n" if lines else ""), encoding="utf-8")


def write_env(path: Path, values: dict[str, Any]) -> None:
    lines = []
    for key, value in values.items():
        if value is None:
            continue
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key}="{escaped}"')
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync dashboard strategy/account records into Steven loop config")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--loop-root", default="/opt/steven-jiao-ai-loop")
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--uid", default=DEFAULT_UID)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--min-accounts", type=int, default=1)
    args = parser.parse_args()

    loop_root = Path(args.loop_root)
    output_dir = Path(args.output_dir) if args.output_dir else loop_root / "config" / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)

    tables = {
        "fb_account_claims": fetch_table(args.api_base, "ai_loop_fb_account_claims"),
        "publish_strategies": fetch_table(args.api_base, "ai_loop_publish_strategies"),
        "clip_strategies": fetch_table(args.api_base, "ai_loop_clip_strategies"),
        "account_selection_strategies": fetch_table(args.api_base, "ai_loop_account_selection_strategies"),
        "drama_selection_strategies": fetch_table(args.api_base, "ai_loop_drama_selection_strategies"),
    }

    accounts = active_owner_accounts(tables["fb_account_claims"], args.owner)
    if len(accounts) < args.min_accounts:
        raise SystemExit(f"not enough accounts for {args.owner}: {len(accounts)} < {args.min_accounts}")

    group_a, group_b = split_ab(accounts)
    synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    all_ids_path = output_dir / "dashboard-steven-team-ids.txt"
    a_ids_path = output_dir / "dashboard-steven-ab-A-team-ids.txt"
    b_ids_path = output_dir / "dashboard-steven-ab-B-team-ids.txt"
    strategy_path = output_dir / "dashboard-strategy-snapshot.json"
    language_path = output_dir / "dashboard-steven-team-languages.json"
    env_path = output_dir / "dashboard-loop-strategy.env"

    write_team_ids(all_ids_path, accounts)
    write_team_ids(a_ids_path, group_a)
    write_team_ids(b_ids_path, group_b)

    language_payload = load_existing_team_languages(loop_root)
    team_languages = language_payload.setdefault("team_languages", {})
    for account in accounts:
        team_languages[account["team_id"]] = {
            "language": "2",
            "source": "dashboard_fb_account_claims",
            "sample_count": 0,
            "success_sample_count": 0,
            "language_counts": {},
            "success_language_counts": {},
            "account_id": account.get("social_account_id"),
            "social_account_id": account.get("social_account_id"),
            "social_name": account.get("social_name"),
            "channel_id": account.get("channel_id"),
            "owner": args.owner,
            "uid": args.uid,
            "allocated_at": account.get("allocated_at"),
        }
    language_path.write_text(json.dumps(language_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    strategy_snapshot = {
        "owner": args.owner,
        "uid": args.uid,
        "synced_at": synced_at,
        "account_pool": {
            "source_table": "ai_loop_fb_account_claims",
            "total": len(accounts),
            "group_a": len(group_a),
            "group_b": len(group_b),
        },
        "execution_mapping": {
            "account_pool": "enabled",
            "ab_split": "enabled",
            "publish_strategy": "metadata_only",
            "clip_strategy": "metadata_only",
            "account_selection_strategy": "metadata_only",
            "drama_selection_strategy": "metadata_only",
        },
        "strategies": {
            "publish": tables["publish_strategies"],
            "clip": tables["clip_strategies"],
            "account_selection": tables["account_selection_strategies"],
            "drama_selection": tables["drama_selection_strategies"],
        },
    }
    strategy_path.write_text(json.dumps(strategy_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    write_env(
        env_path,
        {
            "STEVEN_LOOP_STRATEGY_SOURCE": "dashboard",
            "STEVEN_LOOP_STRATEGY_OWNER": args.owner,
            "STEVEN_LOOP_STRATEGY_UID": args.uid,
            "STEVEN_LOOP_STRATEGY_SYNCED_AT": synced_at,
            "STEVEN_LOOP_STRATEGY_SNAPSHOT_FILE": strategy_path,
            "STEVEN_LOOP_TEAM_LANGUAGE_FILE": language_path,
            "STEVEN_LOOP_TEAM_IDS_FILE": all_ids_path,
            "STEVEN_LOOP_AB_ALL_TEAM_IDS_FILE": all_ids_path,
            "STEVEN_LOOP_AB_GROUP_A_TEAM_IDS_FILE": a_ids_path,
            "STEVEN_LOOP_AB_GROUP_B_TEAM_IDS_FILE": b_ids_path,
            "STEVEN_LOOP_AB_GROUP_A_COUNT": len(group_a),
            "STEVEN_LOOP_AB_GROUP_B_COUNT": len(group_b),
            "STEVEN_LOOP_COUNT": len(accounts),
            "STEVEN_LOOP_MIN_SUCCESS_TARGET": len(accounts) * 10,
        },
    )

    print(
        json.dumps(
            {
                "owner": args.owner,
                "accounts": len(accounts),
                "group_a": len(group_a),
                "group_b": len(group_b),
                "output_dir": str(output_dir),
                "env_file": str(env_path),
                "strategy_snapshot": str(strategy_path),
                "synced_at": synced_at,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
