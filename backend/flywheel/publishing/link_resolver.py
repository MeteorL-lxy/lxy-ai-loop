from __future__ import annotations

import json
from typing import Any

from inbeidou_cli import (
    PROMOTION_PLATFORMS,
    active_task,
    build_promotion_link_entry,
    receive_task,
    require_success,
)


PUBLISH_TO_PROMOTION_PLATFORM = {
    "TIKTOK": 1,
    "FACEBOOK": 2,
    "INSTAGRAM": 3,
    "YOUTUBE": 4,
}
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


def build_placeholder_link(serial_id: str, agent_id: str) -> str:
    return f"https://creator.inbeidou.cn/promo/{serial_id}?agent_id={agent_id or 'pending'}"


def _pick_promotion_link(link_entry: dict[str, Any], *, prefer_app_link: bool, serial_id: str, agent_id: str) -> str:
    if prefer_app_link:
        return (
            str(link_entry.get("app_link") or "").strip()
            or str(link_entry.get("serial_link") or "").strip()
            or str(link_entry.get("tiktok_url") or "").strip()
            or build_placeholder_link(serial_id, agent_id)
        )
    return (
        str(link_entry.get("serial_link") or "").strip()
        or str(link_entry.get("app_link") or "").strip()
        or str(link_entry.get("tiktok_url") or "").strip()
        or build_placeholder_link(serial_id, agent_id)
    )


def _parse_history_payload(drama: dict[str, Any]) -> dict[str, Any]:
    history_payload = drama.get("history_payload")
    if isinstance(history_payload, str):
        try:
            history_payload = json.loads(history_payload or "{}")
        except Exception:
            history_payload = {}
    return history_payload if isinstance(history_payload, dict) else {}


def attach_links(plans: list[dict[str, Any]], drama_map: dict[str, dict[str, Any]], *, dry_run: bool) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for plan in plans:
        updated = dict(plan)
        drama = drama_map.get(str(plan.get("serial_id") or ""), {})
        history_payload = _parse_history_payload(drama)
        publish_platform = str(plan.get("platform") or "").upper()
        promotion_platform = PUBLISH_TO_PROMOTION_PLATFORM.get(publish_platform)
        if dry_run and not promotion_platform:
            updated["promotion_link"] = build_placeholder_link(str(plan.get("serial_id") or ""), str(plan.get("agent_id") or ""))
            updated["caption"] = _compose_caption_with_intro("", str(updated.get("promotion_link") or ""))
            updated["promotion_platform_id"] = ""
            updated["promote_code_content"] = ""
            enriched.append(updated)
            continue

        task_id = drama.get("task_id")
        if task_id and promotion_platform:
            payload = require_success(
                receive_task(task_id=task_id, task_type=drama.get("task_type", "1"), platform=promotion_platform),
                f"获取 {PROMOTION_PLATFORMS[promotion_platform]} 推广链接",
            )
            atr_id = payload.get("atr_id")
            if atr_id:
                require_success(
                    active_task(atr_id),
                    f"激活 {PROMOTION_PLATFORMS[promotion_platform]} 推广任务",
                )
            link_entry = build_promotion_link_entry(promotion_platform, payload)
            updated["promotion_link"] = _pick_promotion_link(
                link_entry,
                prefer_app_link=False,
                serial_id=str(plan.get("serial_id") or ""),
                agent_id=str(plan.get("agent_id") or ""),
            )
            updated["promotion_code"] = link_entry.get("code") or ""
            updated["promotion_platform_id"] = str(promotion_platform or "")
            updated["promote_code_content"] = str(link_entry.get("promote_code_content") or "").strip()
            updated["caption"] = _compose_caption_with_intro(
                str(link_entry.get("promote_code_content") or "").strip(),
                str(updated.get("promotion_link") or ""),
            )
        else:
            anchor = history_payload.get("promotion_anchor") if isinstance(history_payload.get("promotion_anchor"), dict) else {}
            anchor_task_id = str(anchor.get("task_id") or "").strip()
            drama_app_id = str(drama.get("app_id") or plan.get("app_id") or "").strip()
            anchor_app_id = str(anchor.get("app_id") or "").strip()
            if anchor_task_id and promotion_platform and anchor_app_id and (not drama_app_id or anchor_app_id == drama_app_id):
                payload = require_success(
                    receive_task(task_id=anchor_task_id, task_type=anchor.get("task_type", "1"), platform=promotion_platform),
                    f"获取 {PROMOTION_PLATFORMS[promotion_platform]} 推广链接",
                )
                atr_id = payload.get("atr_id")
                if atr_id:
                    require_success(
                        active_task(atr_id),
                        f"激活 {PROMOTION_PLATFORMS[promotion_platform]} 推广任务",
                    )
                link_entry = build_promotion_link_entry(promotion_platform, payload)
                updated["promotion_link"] = _pick_promotion_link(
                    link_entry,
                    prefer_app_link=True,
                    serial_id=str(plan.get("serial_id") or ""),
                    agent_id=str(plan.get("agent_id") or ""),
                )
                updated["promotion_code"] = link_entry.get("code") or ""
                updated["promotion_platform_id"] = str(promotion_platform or "")
                updated["promote_code_content"] = str(link_entry.get("promote_code_content") or "").strip()
                updated["caption"] = _compose_caption_with_intro(
                    str(link_entry.get("promote_code_content") or "").strip(),
                    str(updated.get("promotion_link") or ""),
                )
                updated["promotion_anchor_used"] = True
                updated["promotion_anchor_task_id"] = anchor_task_id
                updated["promotion_anchor_app_id"] = anchor_app_id
                updated["promotion_link_mode"] = "anchor_app_link"
            else:
                updated["promotion_link"] = build_placeholder_link(str(plan.get("serial_id") or ""), str(plan.get("agent_id") or ""))
                updated["caption"] = _compose_caption_with_intro("", str(updated.get("promotion_link") or ""))
                updated["promotion_platform_id"] = str(promotion_platform or "")
                updated["promote_code_content"] = ""
        enriched.append(updated)
    return enriched
