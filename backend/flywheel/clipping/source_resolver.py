from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .episode_selector import select_best_episode


def _parse_history_payload(pick: dict[str, Any]) -> dict[str, Any]:
    history_payload = pick.get("history_payload")
    if isinstance(history_payload, str):
        try:
            history_payload = json.loads(history_payload or "{}")
        except Exception:
            history_payload = {}
    return history_payload if isinstance(history_payload, dict) else {}


def plan_source_jobs(
    *,
    round_id: int,
    picks: list[dict[str, Any]],
    source_dir: str | Path,
    episode_order: int | None,
) -> list[dict[str, Any]]:
    base_dir = Path(source_dir) / f"round_{round_id}"
    jobs: list[dict[str, Any]] = []
    for pick in picks:
        app_id = str(pick.get("app_id") or "")
        history_payload = _parse_history_payload(pick)
        source_mode = str(history_payload.get("source_mode") or pick.get("source_mode") or "").strip()
        external_video_url = str(history_payload.get("external_video_url") or "").strip()
        if source_mode == "external_video":
            jobs.append(
                {
                    "serial_id": pick.get("serial_id"),
                    "title": pick.get("title"),
                    "app_id": app_id,
                    "episode_order": 1,
                    "source_mode": "external_video",
                    "external_video_url": external_video_url,
                    "episode_selection": {
                        "episode_order": 1,
                        "episode_count": 1,
                        "selection_mode": "external_video",
                        "reason": "realtime_rank_external_video",
                        "supported": bool(external_video_url),
                        "candidates": [],
                    },
                    "planned_source_path": str(base_dir / f"{pick.get('serial_id')}_external.mp4"),
                }
            )
            continue
        if episode_order is None:
            episode_decision = select_best_episode(str(pick.get("serial_id") or ""), app_id)
            selected_episode = int(episode_decision.get("episode_order") or 1)
        else:
            selected_episode = int(episode_order)
            episode_decision = {
                "episode_order": selected_episode,
                "episode_count": 0,
                "selection_mode": "forced_episode_order",
                "reason": "configured_or_user_forced_episode_order",
                "supported": True,
                "candidates": [],
            }
        jobs.append(
            {
                "serial_id": pick.get("serial_id"),
                "title": pick.get("title"),
                "app_id": app_id,
                "episode_order": selected_episode,
                "source_mode": "official",
                "external_video_url": "",
                "episode_selection": episode_decision,
                "planned_source_path": str(base_dir / f"{pick.get('serial_id')}_E{selected_episode:02d}.mp4"),
            }
        )
    return jobs
