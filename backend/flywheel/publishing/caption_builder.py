from __future__ import annotations

from typing import Any


def build_caption(plan: dict[str, Any], drama: dict[str, Any]) -> str:
    existing = str(plan.get("caption") or "").strip()
    if existing:
        return existing
    promotion_link = str(plan.get("promotion_link") or "").strip()
    if promotion_link:
        return promotion_link
    return str(drama.get("title") or "").strip()


def attach_captions(plans: list[dict[str, Any]], drama_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for plan in plans:
        drama = drama_map.get(str(plan.get("serial_id") or ""), {})
        updated = dict(plan)
        updated["caption"] = build_caption(updated, drama)
        enriched.append(updated)
    return enriched
