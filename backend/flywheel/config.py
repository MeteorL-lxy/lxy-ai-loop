from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "conf" / "flywheel.yaml"


@dataclass
class FlywheelConfig:
    raw: dict[str, Any]
    path: Path

    @property
    def database_path(self) -> Path:
        return Path(self.raw["local_db"]["path"])

    @property
    def logs_dir(self) -> Path:
        return Path(self.raw["paths"]["logs_dir"])

    @property
    def source_dir(self) -> Path:
        return Path(self.raw["paths"]["source_dir"])

    @property
    def clipped_dir(self) -> Path:
        return Path(self.raw["paths"]["clipped_dir"])

    @property
    def covers_dir(self) -> Path:
        return Path(self.raw["paths"]["covers_dir"])

    @property
    def candidate_pool_size(self) -> int:
        return int(self.raw["flywheel"]["candidate_pool_size"])

    @property
    def candidate_page_size(self) -> int:
        return int(self.raw["flywheel"]["candidate_page_size"])

    @property
    def default_platform(self) -> str:
        return str(self.raw["flywheel"]["default_platform"])

    @property
    def default_language(self) -> str:
        return str(self.raw["flywheel"]["default_language"])

    @property
    def candidate_language_mode(self) -> str:
        return str(self.raw["flywheel"].get("candidate_language_mode", "single")).strip().lower() or "single"

    @property
    def candidate_languages(self) -> list[str]:
        values = self.raw["flywheel"].get("candidate_languages", [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, Iterable):
            normalized = [str(value).strip() for value in values if str(value).strip()]
            if normalized:
                return normalized
        return [self.default_language]

    @property
    def default_order(self) -> str:
        return str(self.raw["flywheel"]["default_order"])

    @property
    def scoring_weights(self) -> dict[str, float]:
        return dict(self.raw["scoring"]["weights"])

    @property
    def realtime_rank_enabled(self) -> bool:
        override = os.getenv("BARRY_REALTIME_RANK_ENABLED")
        if override is not None and str(override).strip() != "":
            return str(override).strip().lower() in {"1", "true", "yes", "on"}
        return bool(self.raw.get("realtime_rank", {}).get("enabled", False))

    @property
    def realtime_rank_timeout_seconds(self) -> float:
        override = os.getenv("BARRY_REALTIME_RANK_TIMEOUT_SECONDS")
        if override is not None and str(override).strip() != "":
            return float(override)
        return float(self.raw.get("realtime_rank", {}).get("timeout_seconds", 20))

    @property
    def realtime_rank_max_candidates(self) -> int:
        return max(0, int(self.raw.get("realtime_rank", {}).get("max_candidates", self.candidate_pool_size)))

    @property
    def realtime_rank_external_first(self) -> bool:
        override = os.getenv("BARRY_REALTIME_EXTERNAL_FIRST")
        if override is not None and str(override).strip() != "":
            return str(override).strip().lower() in {"1", "true", "yes", "on"}
        return bool(self.raw.get("realtime_rank", {}).get("external_first", True))

    @property
    def tier_quota(self) -> dict[str, float]:
        return {key: float(value) for key, value in self.raw["selection"]["tier_quota"].items()}

    @property
    def recent_hard_exclusion_rounds(self) -> int:
        return int(self.raw["selection"].get("recent_hard_exclusion_rounds", 20))

    @property
    def recent_hard_exclusion_days(self) -> int:
        return int(self.raw["selection"].get("recent_hard_exclusion_days", 7))

    @property
    def default_episode_order(self) -> int:
        return int(self.raw["clipping"]["default_episode_order"])

    @property
    def require_third_serial_id(self) -> bool:
        return bool(self.raw["clipping"].get("require_third_serial_id", True))

    @property
    def cut_type(self) -> str:
        return str(self.raw["clipping"]["cut_type"])

    @property
    def clip_duration(self) -> str:
        return str(self.raw["clipping"]["duration"])

    @property
    def clip_output_count(self) -> int:
        return int(self.raw["clipping"]["output_count"])

    @property
    def dedup_pool(self) -> list[str]:
        return list(self.raw["clipping"]["dedup_pool"])

    @property
    def source_prepare_retry_count(self) -> int:
        return max(0, int(self.raw["clipping"].get("source_prepare_retry_count", 0)))

    @property
    def clip_submit_timeout(self) -> int:
        return int(self.raw["clipping"].get("submit_timeout", 90))

    @property
    def clip_task_timeout(self) -> int:
        return int(self.raw["clipping"].get("task_timeout", 1800))

    @property
    def clip_poll_interval(self) -> float:
        return float(self.raw["clipping"].get("poll_interval", 3))

    @property
    def clip_execute_concurrency(self) -> int:
        return max(1, int(self.raw["runtime"].get("clip_execute_concurrency", 1)))

    @property
    def clip_target_width(self) -> int:
        return int(self.raw["clipping"].get("target_width", 720))

    @property
    def clip_target_height(self) -> int:
        return int(self.raw["clipping"].get("target_height", 1280))

    @property
    def publish_execute_concurrency(self) -> int:
        return max(1, int(self.raw["runtime"].get("publish_execute_concurrency", 1)))

    @property
    def default_publish_platforms(self) -> list[str]:
        values = self.raw["runtime"].get("default_publish_platforms", [])
        if isinstance(values, list):
            return [str(value) for value in values if str(value).strip()]
        return []

    @property
    def collect_wait_seconds(self) -> int:
        return int(self.raw["runtime"].get("collect_wait_seconds", 360))

    @property
    def collect_poll_interval(self) -> int:
        return int(self.raw["runtime"].get("collect_poll_interval", 15))

    @property
    def collect_settle_timeout_seconds(self) -> int:
        return int(self.raw["runtime"].get("collect_settle_timeout_seconds", 21600))

    @property
    def cleanup_local_clips_after_publish(self) -> bool:
        return bool(self.raw["runtime"].get("cleanup_local_clips_after_publish", True))


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root() / path


def load_config(path: str | Path | None = None) -> FlywheelConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw_text = config_path.read_text(encoding="utf-8")
    data = json.loads(raw_text)

    normalized = dict(data)
    normalized["local_db"] = dict(data["local_db"])
    normalized["paths"] = dict(data["paths"])

    normalized["local_db"]["path"] = str(resolve_path(data["local_db"]["path"]))
    for key in ("logs_dir", "source_dir", "clipped_dir", "covers_dir"):
        normalized["paths"][key] = str(resolve_path(data["paths"][key]))

    return FlywheelConfig(raw=normalized, path=config_path)
