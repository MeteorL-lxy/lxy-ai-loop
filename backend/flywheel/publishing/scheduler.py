from __future__ import annotations

from typing import Any


def attach_schedule(plans: list[dict[str, Any]], *, immediate: bool = True) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for plan in plans:
        updated = dict(plan)
        updated["scheduled_at"] = None if immediate else updated.get("scheduled_at")
        enriched.append(updated)
    return enriched
