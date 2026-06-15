#!/usr/bin/env python3
"""Pull dashboard strategies/account pool into a loop-ready bundle."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_API_BASE = os.getenv("AI_LOOP_DASHBOARD_API", "http://124.174.76.6")
STRATEGY_TABLES = {
    "clip": "ai_loop_clip_strategies",
    "publish": "ai_loop_publish_strategies",
    "account_selection": "ai_loop_account_selection_strategies",
    "drama_selection": "ai_loop_drama_selection_strategies",
}
NEGATIVE_STATUS = {"disabled", "pause", "paused", "stop", "stopped", "inactive", "已暂停", "停用", "关闭"}


def fetch_table(api_base: str, table: str, limit: int = 100000, *, required: bool = True) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"limit": limit})
    url = f"{api_base.rstrip('/')}/api/table/{urllib.parse.quote(table)}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            payload = json.load(resp)
    except Exception:
        if required:
            raise
        return []
    if not payload.get("ok"):
        if required:
            raise RuntimeError(f"{table}: {payload.get('error') or payload}")
        return []
    rows = payload.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


def text(value: Any) -> str:
    return str(value or "").strip()


def number(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").replace("%", ""))
    except ValueError:
        return 0.0


def parse_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    raw = text(value)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def is_active(row: dict[str, Any]) -> bool:
    status = text(row.get("status") or row.get("state") or row.get("binding_status")).lower()
    return status not in NEGATIVE_STATUS


def claim_matches(row: dict[str, Any], owner: str, uid: str, account_type: str) -> bool:
    if owner and text(row.get("owner")) != owner:
        return False
    if uid and text(row.get("user_id") or row.get("uid")) != uid:
        return False
    if account_type and text(row.get("account_type")).upper() != account_type.upper():
        return False
    return not text(row.get("deleted_at"))


def normalize_accounts(rows: list[dict[str, Any]], *, owner: str, uid: str, account_type: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    accounts: list[dict[str, Any]] = []
    for row in rows:
        if not claim_matches(row, owner, uid, account_type):
            continue
        team_id = text(row.get("team_id"))
        if not team_id or team_id in seen:
            continue
        seen.add(team_id)
        accounts.append(
            {
                "team_id": team_id,
                "social_account_id": text(row.get("social_account_id")),
                "social_name": text(row.get("social_name")) or "Facebook 账号",
                "channel_id": text(row.get("channel_id")),
                "owner": text(row.get("owner")) or owner,
                "uid": text(row.get("user_id") or row.get("uid")) or uid,
                "account_type": text(row.get("account_type")) or account_type,
                "allocated_at": text(row.get("allocated_at")),
                "status": text(row.get("status")),
                "source_claim_id": row.get("claim_id"),
            }
        )
    return accounts


def split_ab(accounts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "A": [account for index, account in enumerate(accounts) if index % 2 == 0],
        "B": [account for index, account in enumerate(accounts) if index % 2 == 1],
    }


def evidence_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        strategy_type = text(row.get("strategy_type"))
        strategy_code = text(row.get("strategy_code"))
        if not strategy_type or not strategy_code:
            continue
        key = (strategy_type, strategy_code)
        current = indexed.get(key)
        if current is None or number(row.get("score")) > number(current.get("score")):
            indexed[key] = row
    return indexed


def normalize_strategy(row: dict[str, Any], strategy_type: str, evidence: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    code = text(row.get("strategy_code") or row.get("category") or row.get("strategy_name"))
    name = text(row.get("strategy_name") or row.get("dimension") or row.get("selection_strategy") or code)
    ev = evidence.get((strategy_type, code), {})
    score = number(ev.get("score"))
    return {
        "strategy_type": strategy_type,
        "strategy_code": code,
        "strategy_name": name,
        "owner": text(row.get("owner")),
        "params": parse_json(row.get("params_json") or row.get("params") or row.get("rule_json")),
        "note": text(row.get("note") or row.get("description") or row.get("raw_text")),
        "sequence": row.get("sequence"),
        "status": text(row.get("status") or row.get("state")) or "active",
        "evidence_level": text(ev.get("evidence_level")) or "metadata_only",
        "binding_status": text(ev.get("binding_status")),
        "score": score,
        "usage_count": int(number(ev.get("usage_count"))),
        "success_count": int(number(ev.get("success_count") or ev.get("success_videos"))),
        "failed_count": int(number(ev.get("failed_count") or ev.get("failed_videos"))),
        "source_table": STRATEGY_TABLES[strategy_type],
        "source_row": row.get("source_row"),
    }


def sequence_value(row: dict[str, Any]) -> int:
    try:
        return int(row.get("sequence") or 999999)
    except (TypeError, ValueError):
        return 999999


def write_team_ids(path: Path, accounts: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [account["team_id"] for account in accounts if account.get("team_id")]
    path.write_text("\n".join(lines).rstrip() + ("\n" if lines else ""), encoding="utf-8")


def write_env(path: Path, bundle: dict[str, Any], team_ids_path: str) -> None:
    selected = bundle.get("selected_strategies") or {}
    values = {
        "AI_LOOP_STRATEGY_SOURCE": "dashboard",
        "AI_LOOP_OWNER": bundle.get("owner"),
        "AI_LOOP_UID": bundle.get("uid"),
        "AI_LOOP_NAME": bundle.get("loop_name"),
        "AI_LOOP_STRATEGY_BUNDLE_FILE": str(bundle.get("_bundle_file") or ""),
        "AI_LOOP_TEAM_IDS_FILE": team_ids_path,
        "AI_LOOP_ACCOUNT_COUNT": bundle.get("account_pool", {}).get("total"),
    }
    for strategy_type, strategy in selected.items():
        prefix = f"AI_LOOP_{strategy_type.upper()}_STRATEGY"
        values[f"{prefix}_CODE"] = strategy.get("strategy_code")
        values[f"{prefix}_NAME"] = strategy.get("strategy_name")
    lines = []
    for key, value in values.items():
        escaped = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key}="{escaped}"')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull dashboard strategy/account records into a loop-ready JSON bundle")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--uid", default="")
    parser.add_argument("--loop-name", default=os.getenv("AI_LOOP_NAME", "custom-loop"))
    parser.add_argument("--account-type", default="FACEBOOK")
    parser.add_argument("--strategy-type", action="append", choices=sorted(STRATEGY_TABLES), help="Repeat to limit strategy types")
    parser.add_argument("--strategy-owner", default="", help="Optional strategy owner filter. Empty keeps shared strategy pool")
    parser.add_argument("--top", type=int, default=1, help="How many recommended strategies to keep per type")
    parser.add_argument("--output", default="", help="Write strategy bundle JSON")
    parser.add_argument("--env-output", default="", help="Write env file for shell-based loops")
    parser.add_argument("--team-ids-output", default="", help="Write team_id list for loop account pools")
    parser.add_argument("--min-accounts", type=int, default=0)
    args = parser.parse_args()

    selected_types = args.strategy_type or list(STRATEGY_TABLES)
    evidence = evidence_index(fetch_table(args.api_base, "ai_loop_strategy_bindings", required=False))
    claims = fetch_table(args.api_base, "ai_loop_fb_account_claims")
    accounts = normalize_accounts(claims, owner=args.owner, uid=args.uid, account_type=args.account_type)
    if len(accounts) < args.min_accounts:
        raise SystemExit(f"not enough accounts for {args.owner}: {len(accounts)} < {args.min_accounts}")

    strategies: dict[str, list[dict[str, Any]]] = {}
    selected: dict[str, dict[str, Any]] = {}
    recommended: dict[str, list[dict[str, Any]]] = {}
    for strategy_type in selected_types:
        rows = fetch_table(args.api_base, STRATEGY_TABLES[strategy_type])
        normalized = []
        for row in rows:
            if not is_active(row):
                continue
            if args.strategy_owner and text(row.get("owner")) != args.strategy_owner:
                continue
            item = normalize_strategy(row, strategy_type, evidence)
            if item["strategy_code"]:
                normalized.append(item)
        normalized.sort(key=lambda item: (-number(item.get("score")), sequence_value(item), item.get("strategy_code") or ""))
        strategies[strategy_type] = normalized
        recommended[strategy_type] = normalized[: max(args.top, 0)]
        if normalized:
            selected[strategy_type] = normalized[0]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bundle: dict[str, Any] = {
        "schema_version": "strategy-bundle-v2",
        "generated_at": generated_at,
        "api_base": args.api_base.rstrip("/"),
        "owner": args.owner,
        "uid": args.uid,
        "loop_name": args.loop_name,
        "account_pool": {
            "source_table": "ai_loop_fb_account_claims",
            "account_type": args.account_type,
            "total": len(accounts),
            "accounts": accounts,
            "ab_groups": split_ab(accounts),
        },
        "strategies": strategies,
        "recommended_strategies": recommended,
        "selected_strategies": selected,
        "usage_protocol": {
            "before_loop": "pull bundle, select strategy, then claim binding",
            "during_loop": "write strategy codes into task clip_params.strategy_context",
            "after_loop": "push task results and runtime events through API",
        },
    }

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        bundle["_bundle_file"] = str(output)
        output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.team_ids_output:
        write_team_ids(Path(args.team_ids_output), accounts)

    if args.env_output:
        write_env(Path(args.env_output), bundle, args.team_ids_output)

    print(json.dumps({
        "ok": True,
        "owner": args.owner,
        "uid": args.uid,
        "loop_name": args.loop_name,
        "accounts": len(accounts),
        "selected_strategies": {k: v.get("strategy_code") for k, v in selected.items()},
        "output": args.output,
        "env_output": args.env_output,
        "team_ids_output": args.team_ids_output,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
