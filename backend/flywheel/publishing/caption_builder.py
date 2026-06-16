from __future__ import annotations

from typing import Any


PROMOTION_INTRO_LINE = "👇 Click the link below to watch the full episode!"


def _compose_caption_with_intro(base_text: str, promotion_link: str) -> str:
    intro = PROMOTION_INTRO_LINE
    text = str(base_text or "").strip()
    link = str(promotion_link or "").strip()
    if text.startswith(intro):
        return text
    if text and link and link in text:
        body = text
    elif text and link:
        body = f"{link}\n{text}"
    else:
        body = text or link
    if not body:
        return intro
    return f"{intro}\n{body}"


def build_caption(plan: dict[str, Any], drama: dict[str, Any]) -> str:
    existing = str(plan.get("caption") or "").strip()
    promotion_link = str(plan.get("promotion_link") or "").strip()
    if existing:
        return _compose_caption_with_intro(existing, promotion_link)
    if promotion_link:
        return _compose_caption_with_intro("", promotion_link)
    return _compose_caption_with_intro(str(drama.get("title") or "").strip(), "")


def attach_captions(plans: list[dict[str, Any]], drama_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for plan in plans:
        drama = drama_map.get(str(plan.get("serial_id") or ""), {})
        updated = dict(plan)
        updated["caption"] = build_caption(updated, drama)
        enriched.append(updated)
    return enriched
