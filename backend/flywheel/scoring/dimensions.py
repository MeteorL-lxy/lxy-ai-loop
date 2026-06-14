from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def parse_tags(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def parse_publish_at(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    for candidate in (raw, raw.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    return None


def proven_proxy_score(item: dict[str, Any]) -> float:
    share_rate = max(0.0, min(1.0, safe_float(item.get("share_rate")) / 100.0))
    promoter_number = safe_float(item.get("promoter_number"))
    promoter_norm = min(1.0, promoter_number / 50.0)
    hot_bonus = 0.15 if item.get("hot_content") else 0.0
    return min(1.0, 0.55 * share_rate + 0.30 * promoter_norm + hot_bonus)


def cluster_score(item: dict[str, Any], pool: list[dict[str, Any]]) -> float:
    current_tags = set(parse_tags(item.get("tag")))
    same_cluster: list[dict[str, Any]] = []
    fallback_cluster: list[dict[str, Any]] = []
    for candidate in pool:
        if candidate is item:
            continue
        if str(candidate.get("language")) == str(item.get("language")) and str(candidate.get("app_id")) == str(item.get("app_id")):
            fallback_cluster.append(candidate)
            if current_tags & set(parse_tags(candidate.get("tag"))):
                same_cluster.append(candidate)

    target_cluster = same_cluster if len(same_cluster) >= 3 else fallback_cluster
    if not target_cluster:
        return 0.35
    average = sum(proven_proxy_score(candidate) for candidate in target_cluster) / len(target_cluster)
    return min(1.0, average)


def content_score(item: dict[str, Any]) -> float:
    score = 0.0
    description = str(item.get("description") or item.get("description_en") or "")
    if len(description.strip()) >= 40:
        score += 0.20
    if item.get("cover") or item.get("third_cover"):
        score += 0.10
    if item.get("hot_content"):
        score += 0.15
    if item.get("payment_content"):
        score += 0.05
    if safe_float(item.get("episode_count")) >= 10:
        score += 0.15
    if len(parse_tags(item.get("tag"))) >= 3:
        score += 0.10
    if item.get("title_en") or item.get("third_serial_id"):
        score += 0.10
    if safe_float(item.get("share_rate")) >= 60:
        score += 0.05
    if safe_float(item.get("promoter_number")) > 0:
        score += 0.10
    return min(1.0, score)


def freshness_score(item: dict[str, Any]) -> float:
    publish_at = parse_publish_at(item.get("publish_at"))
    if publish_at is None:
        return 0.0
    now = datetime.now(timezone.utc)
    days = max(0.0, (now - publish_at).total_seconds() / 86400.0)
    return math.exp(-days / 14.0)


def scarcity_score(item: dict[str, Any]) -> float:
    n_pushers = safe_float(item.get("promoter_number"))
    if n_pushers <= 0:
        return 0.4
    if n_pushers <= 2:
        return 0.7
    if n_pushers <= 10:
        return 1.0
    if n_pushers <= 30:
        return 0.6
    if n_pushers <= 100:
        return 0.2
    return 0.1


def editor_score(item: dict[str, Any]) -> float:
    base = 0.25
    if str(item.get("tag") or "").strip().lower() == "hot":
        base += 0.20
    if item.get("hot_content"):
        base += 0.25
    if item.get("payment_content"):
        base += 0.10
    weight = safe_float(item.get("weight"))
    if weight > 0:
        base += min(0.20, max(0.0, (weight - 1000.0) / 1000.0) * 0.20)
    return min(1.0, base)

