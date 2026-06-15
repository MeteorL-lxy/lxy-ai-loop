#!/usr/bin/env python3
"""Register which dashboard strategies a loop is about to execute."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_API_BASE = os.getenv("AI_LOOP_DASHBOARD_API", "http://124.174.76.6")
STRATEGY_TYPES = {"clip", "publish", "account_selection", "drama_selection"}


def text(value: Any) -> str:
    return str(value or "").strip()


def read_json(path: str) -> Any:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def post_rows(api_base: str, table: str, rows: list[dict[str, Any]], api_key: str = "") -> dict[str, Any]:
    body = json.dumps({"table": table, "rows": rows}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(f"{api_base.rstrip('/')}/api/ingest", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def parse_strategy_arg(raw: str) -> dict[str, str]:
    parts = raw.split(":", 2)
    if len(parts) < 2 or parts[0] not in STRATEGY_TYPES:
        raise argparse.ArgumentTypeError("strategy must look like type:code[:name]")
    return {
        "strategy_type": parts[0],
        "strategy_code": parts[1],
        "strategy_name": parts[2] if len(parts) > 2 else parts[1],
    }


def strategies_from_bundle(bundle: dict[str, Any], only_types: set[str]) -> list[dict[str, Any]]:
    selected = bundle.get("selected_strategies") or {}
    rows: list[dict[str, Any]] = []
    for strategy_type, item in selected.items():
        if only_types and strategy_type not in only_types:
            continue
        if not isinstance(item, dict):
            continue
        code = text(item.get("strategy_code"))
        if not code:
            continue
        rows.append(
            {
                "strategy_type": strategy_type,
                "strategy_code": code,
                "strategy_name": text(item.get("strategy_name")) or code,
                "strategy_owner": text(item.get("owner")),
                "score": item.get("score") or 0,
            }
        )
    return rows


def build_rows(args: argparse.Namespace, strategies: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_id = args.run_id or f"{args.loop_name}:{args.owner}:{args.round_name or 'round'}:{now.replace(' ', 'T')}"
    rows: list[dict[str, Any]] = []
    for item in strategies:
        strategy_type = text(item.get("strategy_type"))
        strategy_code = text(item.get("strategy_code"))
        strategy_name = text(item.get("strategy_name")) or strategy_code
        binding_id = f"loop:{run_id}:{strategy_type}:{strategy_code}"
        rows.append(
            {
                "binding_id": binding_id[:255],
                "owner": args.owner,
                "loop_name": args.loop_name,
                "strategy_type": strategy_type,
                "strategy_code": strategy_code,
                "strategy_name": strategy_name,
                "strategy_owner": text(item.get("strategy_owner")) or args.owner,
                "round_name": args.round_name,
                "ab_group": args.ab_group,
                "binding_status": "claimed",
                "evidence_level": "loop_claimed",
                "usage_count": 0,
                "task_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "publish_actions": 0,
                "success_videos": 0,
                "failed_videos": 0,
                "views": 0,
                "link_clicks": 0,
                "orders": 0,
                "commission_amount": 0,
                "score": item.get("score") or 0,
                "source": "video_pipeline_tracker_skill",
                "source_file": args.strategy_bundle or "manual",
                "started_at": now,
                "last_seen_at": now,
                "updated_at": now,
            }
        )
    return run_id, rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Claim dashboard strategy bindings before a loop run")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--api-key", default=os.getenv("INGEST_API_KEY", ""))
    parser.add_argument("--owner", required=True)
    parser.add_argument("--loop-name", required=True)
    parser.add_argument("--round-name", default="")
    parser.add_argument("--ab-group", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--strategy-bundle", default="")
    parser.add_argument("--strategy-type", action="append", choices=sorted(STRATEGY_TYPES), help="Limit bundle selected strategies")
    parser.add_argument("--strategy", action="append", type=parse_strategy_arg, help="Manual strategy, type:code[:name]. Can repeat")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("-o", "--output", default="", help="Write strategy context JSON for the loop")
    args = parser.parse_args()

    only_types = set(args.strategy_type or [])
    strategies: list[dict[str, Any]] = []
    if args.strategy_bundle:
        strategies.extend(strategies_from_bundle(read_json(args.strategy_bundle), only_types))
    if args.strategy:
        strategies.extend(args.strategy)
    if not strategies:
        raise SystemExit("no strategies selected. Provide --strategy-bundle or --strategy")

    run_id, rows = build_rows(args, strategies)
    context = {
        "ok": True,
        "execute": args.execute,
        "strategy_run_id": run_id,
        "owner": args.owner,
        "loop_name": args.loop_name,
        "round_name": args.round_name,
        "ab_group": args.ab_group,
        "strategy_bindings": rows,
        "strategy_context": {
            row["strategy_type"]: {
                "binding_id": row["binding_id"],
                "strategy_type": row["strategy_type"],
                "strategy_code": row["strategy_code"],
                "strategy_name": row["strategy_name"],
            }
            for row in rows
        },
    }

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.execute:
        context["response"] = post_rows(args.api_base, "ai_loop_strategy_bindings", rows, api_key=args.api_key)

    print(json.dumps(context, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
