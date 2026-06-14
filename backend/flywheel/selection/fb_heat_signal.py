from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def _signal_file_path() -> str:
    return str(os.getenv("BARRY_FB_HEAT_SIGNAL_FILE") or "").strip()


@lru_cache(maxsize=8)
def _load_signal_file(path_str: str) -> dict[str, Any]:
    if not path_str:
        return {}
    path = Path(path_str).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_fb_heat_signal() -> dict[str, Any]:
    return _load_signal_file(_signal_file_path())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _title_text(candidate: dict[str, Any]) -> str:
    values = [
        str(candidate.get("title") or "").strip(),
        str(candidate.get("title_ch") or "").strip(),
        str(candidate.get("title_en") or "").strip(),
    ]
    return " ".join(value.lower() for value in values if value)


def apply_fb_heat_signal(candidate: dict[str, Any], signal: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = signal if isinstance(signal, dict) else load_fb_heat_signal()
    if not rules:
        return dict(candidate)

    boost = float(candidate.get("candidate_priority_boost") or 0.0)
    breakdown: dict[str, float] = {}

    serial_boost = _safe_float((rules.get("serial_id_boosts") or {}).get(str(candidate.get("serial_id") or "").strip()))
    if serial_boost:
        boost += serial_boost
        breakdown["serial_id_boost"] = round(serial_boost, 4)

    third_serial_id = str(candidate.get("third_serial_id") or "").strip().lower()
    third_serial_boost = _safe_float((rules.get("third_serial_id_boosts") or {}).get(third_serial_id))
    if third_serial_boost:
        boost += third_serial_boost
        breakdown["third_serial_id_boost"] = round(third_serial_boost, 4)

    app_id = str(candidate.get("app_id") or "").strip().lower()
    app_boost = _safe_float((rules.get("app_id_boosts") or {}).get(app_id))
    if app_boost:
        boost += app_boost
        breakdown["app_id_boost"] = round(app_boost, 4)

    source = str(candidate.get("candidate_fetch_source") or "").strip()
    source_boost = _safe_float((rules.get("fetch_source_boosts") or {}).get(source))
    if source_boost:
        boost += source_boost
        breakdown["fetch_source_boost"] = round(source_boost, 4)

    title_text = _title_text(candidate)
    matched_keywords: list[str] = []
    keyword_total = 0.0
    for row in rules.get("title_keyword_boosts") or []:
        if not isinstance(row, dict):
            continue
        keyword = str(row.get("keyword") or "").strip().lower()
        if not keyword or keyword not in title_text:
            continue
        row_boost = _safe_float(row.get("boost"))
        if row_boost:
            keyword_total += row_boost
            matched_keywords.append(keyword)
    if keyword_total:
        boost += keyword_total
        breakdown["title_keyword_boost"] = round(keyword_total, 4)

    updated = dict(candidate)
    updated["candidate_priority_boost"] = round(boost, 4)
    if breakdown:
        updated["fb_heat_signal"] = {
            "matched_keywords": matched_keywords,
            "breakdown": breakdown,
            "total_boost": round(sum(breakdown.values()), 4),
        }
    return updated
