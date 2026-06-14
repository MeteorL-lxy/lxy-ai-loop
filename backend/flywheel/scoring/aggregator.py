from __future__ import annotations

from typing import Any

from .dimensions import (
    cluster_score,
    content_score,
    editor_score,
    freshness_score,
    proven_proxy_score,
    scarcity_score,
)
from .ucb import ucb_bonus


def score_candidate(
    item: dict[str, Any],
    *,
    pool: list[dict[str, Any]],
    observed_picks: int,
    total_rounds: int,
    weights: dict[str, float],
) -> dict[str, Any]:
    breakdown = {
        "proven_score": round(proven_proxy_score(item), 4),
        "cluster_score": round(cluster_score(item, pool), 4),
        "content_score": round(content_score(item), 4),
        "freshness_score": round(freshness_score(item), 4),
        "scarcity_score": round(scarcity_score(item), 4),
        "editor_score": round(editor_score(item), 4),
        "priority_boost": round(float(item.get("candidate_priority_boost") or 0.0), 4),
        "ucb_bonus": round(ucb_bonus(observed_picks, total_rounds, c=weights.get("ucb_c", 1.0)), 4),
        "observed_picks": observed_picks,
        "score_mode": "proxy_task_page_only",
    }

    final_score = (
        weights.get("alpha", 0.0) * breakdown["proven_score"]
        + weights.get("beta", 0.0) * breakdown["cluster_score"]
        + weights.get("gamma", 0.0) * breakdown["content_score"]
        + weights.get("delta", 0.0) * breakdown["freshness_score"]
        + weights.get("epsilon", 0.0) * breakdown["scarcity_score"]
        + weights.get("zeta", 0.0) * breakdown["editor_score"]
        + breakdown["priority_boost"]
        + weights.get("ucb_c", 1.0) * breakdown["ucb_bonus"] * 0.1
    )
    breakdown["final_score"] = round(min(2.0, max(0.0, final_score)), 4)
    return breakdown
