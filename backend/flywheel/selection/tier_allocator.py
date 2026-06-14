from __future__ import annotations

from math import floor
from typing import Any


TIER_ORDER = ["A", "B", "C", "D"]


def classify_tier(score_breakdown: dict[str, Any]) -> str:
    proven = float(score_breakdown.get("proven_score") or 0.0)
    final_score = float(score_breakdown.get("final_score") or 0.0)
    content = float(score_breakdown.get("content_score") or 0.0)
    freshness = float(score_breakdown.get("freshness_score") or 0.0)
    scarcity = float(score_breakdown.get("scarcity_score") or 0.0)

    if proven >= 0.6 and final_score >= 0.6:
        return "A"
    if final_score >= 0.55 and (freshness >= 0.35 or proven >= 0.35):
        return "B"
    if proven < 0.4 and content >= 0.55 and freshness >= 0.25:
        return "C"
    if scarcity >= 0.7:
        return "D"
    if final_score >= 0.5:
        return "B"
    if content >= 0.45:
        return "C"
    return "D"


def allocate_slots(total_slots: int, tier_quota: dict[str, float]) -> dict[str, int]:
    allocation = {tier: floor(total_slots * tier_quota.get(tier, 0.0)) for tier in TIER_ORDER}
    allocation["A"] += total_slots - sum(allocation.values())
    return allocation


def allocate_candidate_counts(total_candidates: int, tier_quota: dict[str, float]) -> dict[str, int]:
    allocation = {tier: floor(total_candidates * tier_quota.get(tier, 0.0)) for tier in TIER_ORDER}
    remainder = total_candidates - sum(allocation.values())
    for tier in TIER_ORDER:
        if remainder <= 0:
            break
        allocation[tier] += 1
        remainder -= 1
    return allocation


def assign_ranked_tiers(candidates: list[dict[str, Any]], tier_quota: dict[str, float]) -> list[dict[str, Any]]:
    ranked = sorted(candidates, key=lambda item: float(item.get("final_score") or 0.0), reverse=True)
    tier_counts = allocate_candidate_counts(len(ranked), tier_quota)
    index = 0
    assigned: list[dict[str, Any]] = []
    for tier in TIER_ORDER:
        count = tier_counts.get(tier, 0)
        for item in ranked[index : index + count]:
            enriched = dict(item)
            enriched["tier"] = tier
            assigned.append(enriched)
        index += count
    return assigned


def bucket_candidates(candidates: list[dict[str, Any]], total_slots: int, tier_quota: dict[str, float]) -> dict[str, Any]:
    ranked_candidates = assign_ranked_tiers(candidates, tier_quota)
    buckets = {tier: [] for tier in TIER_ORDER}
    for candidate in ranked_candidates:
        tier = candidate.get("tier") or "D"
        buckets.setdefault(tier, []).append(candidate)

    for tier in TIER_ORDER:
        buckets[tier] = sorted(
            buckets.get(tier, []),
            key=lambda item: float(item.get("final_score") or 0.0),
            reverse=True,
        )

    return {
        "slot_allocation": allocate_slots(total_slots, tier_quota),
        "bucket_sizes": {tier: len(buckets.get(tier, [])) for tier in TIER_ORDER},
        "buckets": buckets,
    }
