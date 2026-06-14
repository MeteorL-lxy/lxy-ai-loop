from __future__ import annotations

import math
import time
from typing import Any

from inbeidou_cli import InbeidouError, get_episode_info, get_episode_list, require_success

MAX_EPISODE_DETAIL_PROBES = 4


def _episode_order(row: dict[str, Any]) -> int:
    return int(row.get("episode_order") or row.get("episode_id") or row.get("sequence") or row.get("id") or 0)


def _position_score(order: int, total: int) -> float:
    if total <= 1:
        return 1.0
    position = order / total
    target = 0.28 if total >= 6 else 0.4
    spread = 0.22 if total >= 6 else 0.35
    return max(0.0, 1.0 - abs(position - target) / spread)


def _availability_score(row: dict[str, Any], info: dict[str, Any]) -> float:
    if row.get("play_url") or info.get("play_url") or info.get("mp4_OD") or info.get("m3u8_HD"):
        return 1.0
    return 0.0


def _episode_base_score(order: int, total: int) -> float:
    position = _position_score(order, total)
    non_edge_bonus = 0.15 if 1 < order < total else 0.0
    short_series_boost = 0.1 if total <= 5 and order == min(2, total) else 0.0
    mid_series_boost = 0.15 if total >= 6 and math.ceil(total * 0.18) <= order <= math.ceil(total * 0.4) else 0.0
    return position * 0.3 + non_edge_bonus + short_series_boost + mid_series_boost


def _scored_episode(row: dict[str, Any], info: dict[str, Any], *, total: int) -> dict[str, Any]:
    order = _episode_order(row)
    availability = _availability_score(row, info)
    position = _position_score(order, total)
    score = availability * 0.55 + _episode_base_score(order, total)
    return {
        "episode_order": order,
        "episode_id": row.get("episode_id") or info.get("id") or order,
        "episode_name": row.get("episode_name") or info.get("chapter_name") or f"Episode {order}",
        "play_url": row.get("play_url") or info.get("play_url") or info.get("mp4_OD") or info.get("m3u8_HD") or "",
        "duration": int(row.get("duration") or info.get("duration") or info.get("file_duration") or 0),
        "availability_score": round(availability, 4),
        "position_score": round(position, 4),
        "final_score": round(score, 4),
    }


def _episode_probe_rows(episodes: list[dict[str, Any]], total: int) -> list[dict[str, Any]]:
    ranked = sorted(
        episodes,
        key=lambda row: (_episode_base_score(_episode_order(row), total), -_episode_order(row)),
        reverse=True,
    )
    return ranked[: min(MAX_EPISODE_DETAIL_PROBES, len(ranked))]


def _is_retryable_episode_error(exc: Exception) -> bool:
    text = str(exc or "").strip().lower()
    return any(
        token in text
        for token in (
            "timed out",
            "timeout",
            "read timeout",
            "connect timeout",
            "connection aborted",
            "connection reset",
            "temporarily unavailable",
            "502",
            "503",
            "504",
            "ssl",
        )
    )


def _episode_api_with_retries(loader, *, retry_count: int) -> Any:
    attempts = max(1, int(retry_count or 0) + 1)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return loader()
        except InbeidouError as exc:
            last_error = exc
            if attempt >= attempts - 1 or not _is_retryable_episode_error(exc):
                raise
            time.sleep(min(3, 1 + attempt))
    if last_error:
        raise last_error
    raise InbeidouError("剧集接口调用失败")


def select_best_episode(serial_id: str | int, app_id: str, *, retry_count: int = 0) -> dict[str, Any]:
    try:
        rows = _episode_api_with_retries(
            lambda: require_success(get_episode_list(serial_id=int(serial_id)), "获取短剧剧集列表"),
            retry_count=retry_count,
        )
    except InbeidouError as exc:
        return {
            "episode_order": 1,
            "episode_count": 0,
            "selection_mode": "unsupported_source",
            "reason": str(exc),
            "supported": False,
            "candidates": [],
        }
    episodes = [dict(row) for row in rows if _episode_order(dict(row)) > 0]
    episodes.sort(key=_episode_order)
    if not episodes:
        return {
            "episode_order": 1,
            "episode_count": 0,
            "selection_mode": "fallback_default",
            "reason": "no_episode_rows",
            "supported": False,
            "candidates": [],
        }

    total = len(episodes)
    playable_rows = [row for row in episodes if _availability_score(row, {}) > 0]
    scored = [_scored_episode(row, {}, total=total) for row in playable_rows]

    if not scored:
        for row in _episode_probe_rows(episodes, total):
            order = _episode_order(row)
            try:
                info = _episode_api_with_retries(
                    lambda order=order: require_success(
                        get_episode_info(serial_id=int(serial_id), episode_order=order, app_id=str(app_id)),
                        f"获取第 {order} 集详情",
                    ),
                    retry_count=retry_count,
                )
            except InbeidouError:
                info = {}
            scored.append(_scored_episode(row, info, total=total))

    scored.sort(key=lambda item: (float(item["final_score"]), -int(item["episode_order"])), reverse=True)
    selected = scored[0]
    if float(selected.get("availability_score") or 0) <= 0:
        return {
            "episode_order": 1,
            "episode_count": total,
            "selection_mode": "no_playable_episode",
            "reason": "episode rows exist but no playable mp4/play_url is available for the clipping workflow",
            "supported": False,
            "candidates": scored[: min(10, len(scored))],
        }
    return {
        "episode_order": int(selected["episode_order"]),
        "episode_count": total,
        "episode_id": selected.get("episode_id"),
        "episode_name": selected.get("episode_name"),
        "play_url": selected.get("play_url") or "",
        "duration": int(selected.get("duration") or 0),
        "selection_mode": "position_availability_heuristic",
        "reason": (
            "Prefer episodes with playable assets and strong hook position, "
            "biasing toward the early-middle section instead of always Episode 1."
        ),
        "supported": True,
        "candidates": scored[: min(10, len(scored))],
    }
