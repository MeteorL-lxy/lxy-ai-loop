from __future__ import annotations

import json
from typing import Any

from .tier_allocator import allocate_slots


DEFAULT_PICK_LIMITS = {"A": 3, "B": 3, "C": 3, "D": 2}


def select_dramas(candidate_rows: list[dict[str, Any]], total_slots: int, tier_quota: dict[str, float]) -> list[dict[str, Any]]:
    slot_allocation = allocate_slots(total_slots, tier_quota)
    grouped: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": [], "D": []}
    for row in candidate_rows:
        grouped.setdefault(str(row.get("tier") or "D"), []).append(row)

    picks: list[dict[str, Any]] = []
    for tier in ("A", "B", "C", "D"):
        ranked = sorted(grouped.get(tier, []), key=lambda item: float(item.get("final_score") or 0.0), reverse=True)
        chosen = ranked[: DEFAULT_PICK_LIMITS[tier]]
        if not chosen:
            continue
        base_slots = slot_allocation[tier] // len(chosen)
        remainder = slot_allocation[tier] % len(chosen)
        for index, item in enumerate(chosen):
                breakdown = item.get("score_breakdown")
                if isinstance(breakdown, str):
                    breakdown = json.loads(breakdown or "{}")
                picks.append(
                    {
                    "serial_id": item.get("serial_id"),
                    "task_id": item.get("task_id"),
                        "title": item.get("title"),
                        "app_id": item.get("app_id"),
                        "language": item.get("language"),
                        "third_serial_id": str(item.get("third_serial_id") or "").strip(),
                        "history_payload": item.get("history_payload") or {},
                        "tier": tier,
                        "final_score": float(item.get("final_score") or 0.0),
                    "score_breakdown": breakdown or {},
                    "slot_count": base_slots + (1 if index < remainder else 0),
                    "ai_reason": (
                        f"Rule selector chose this drama from Tier {tier} based on current proxy score ranking. "
                        "A real LLM selector can replace this in a later round."
                    ),
                    "status": "picked",
                }
            )

    return picks
