from __future__ import annotations

import hashlib
import re
from typing import Any


def candidate_serial_ids(item: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    serial_id = str(item.get("serial_id") or "").strip()
    if serial_id:
        values.add(serial_id)
    variant_serial_ids = item.get("candidate_variant_serial_ids")
    if isinstance(variant_serial_ids, list):
        values.update(str(value).strip() for value in variant_serial_ids if str(value).strip())
    return values


def normalize_title_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return text


def build_title_history_key(app_id: Any, title: Any) -> str:
    normalized_title = normalize_title_token(title)
    normalized_app = str(app_id or "").strip().lower()
    if not normalized_title:
        return ""
    return f"title:{normalized_app}:{normalized_title}"


def build_cross_app_title_history_key(title: Any) -> str:
    normalized_title = normalize_title_token(title)
    if not normalized_title:
        return ""
    return f"title_any:{normalized_title}"


def candidate_history_keys(item: dict[str, Any]) -> set[str]:
    values = {f"serial:{serial_id}" for serial_id in candidate_serial_ids(item)}
    app_id = item.get("app_id")
    third_serial_id = str(item.get("third_serial_id") or "").strip().lower()
    if third_serial_id:
        values.add(f"third_serial:{third_serial_id}")
    realtime_name_md5 = str(item.get("realtime_name_md5") or "").strip().lower()
    if realtime_name_md5:
        values.add(f"realtime_md5:{realtime_name_md5}")
    external_video_url = str(item.get("external_video_url") or "").strip()
    if external_video_url:
        values.add(f"external_video:{hashlib.sha1(external_video_url.encode('utf-8')).hexdigest()}")
    for field in ("title", "title_ch", "title_en", "third_serial_id"):
        key = build_title_history_key(app_id, item.get(field))
        if key:
            values.add(key)
        cross_app_key = build_cross_app_title_history_key(item.get(field))
        if cross_app_key:
            values.add(cross_app_key)
    history_payload = item.get("history_payload")
    if isinstance(history_payload, dict):
        for serial_id in history_payload.get("serial_ids") or []:
            normalized = str(serial_id or "").strip()
            if normalized:
                values.add(f"serial:{normalized}")
        for third_serial in history_payload.get("third_serial_ids") or []:
            normalized = str(third_serial or "").strip().lower()
            if normalized:
                values.add(f"third_serial:{normalized}")
        for title in history_payload.get("titles") or []:
            key = build_title_history_key(app_id, title)
            if key:
                values.add(key)
            cross_app_key = build_cross_app_title_history_key(title)
            if cross_app_key:
                values.add(cross_app_key)
        for extra_key in history_payload.get("external_keys") or []:
            normalized = str(extra_key or "").strip()
            if normalized:
                values.add(normalized)
    return values


def split_recent_candidates(
    candidates: list[dict[str, Any]],
    recent_history_keys: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fresh: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []
    for item in candidates:
        if candidate_history_keys(item) & recent_history_keys:
            recent.append(item)
        else:
            fresh.append(item)
    return fresh, recent
