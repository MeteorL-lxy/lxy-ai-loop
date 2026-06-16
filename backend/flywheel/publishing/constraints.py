from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from inbeidou_cli import InbeidouError, probe_video

MAX_PUBLISH_FILE_SIZE_BYTES = 400 * 1024 * 1024
MIN_SOURCE_DURATION_SECONDS = 30
MAX_SOURCE_DURATION_SECONDS = 900
MAX_PUBLISH_DURATION_SECONDS = 8 * 60
MIN_PUBLISH_WIDTH = 720
MIN_PUBLISH_HEIGHT = 720

PUBLISH_TO_PROMOTION_PLATFORM = {
    "TIKTOK": 1,
    "FACEBOOK": 2,
    "INSTAGRAM": 3,
    "YOUTUBE": 4,
}

PLATFORM_HOST_CONFLICTS = {
    "TIKTOK": ("facebook.com", "fb.watch", "instagram.com", "youtube.com", "youtu.be"),
    "FACEBOOK": ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com", "instagram.com", "youtube.com", "youtu.be"),
    "INSTAGRAM": ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com", "facebook.com", "fb.watch", "youtube.com", "youtu.be"),
    "YOUTUBE": ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com", "facebook.com", "fb.watch", "instagram.com"),
}


def _meta_int(meta: dict[str, Any], key: str) -> int:
    try:
        return int(meta.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def validate_source_episode_constraints(
    episode: dict[str, Any] | None,
    *,
    source_mode: str | None = None,
) -> None:
    row = dict(episode or {})
    duration = (
        _meta_int(row, "duration")
        or _meta_int(row, "file_duration")
        or _meta_int(row, "video_duration")
    )
    if not duration:
        return
    normalized_source_mode = str(source_mode or row.get("selection_mode") or "").strip().lower()
    if normalized_source_mode == "external_video":
        if duration < MIN_SOURCE_DURATION_SECONDS:
            raise InbeidouError(
                f"外部素材时长不符合要求: {duration}s，要求至少 {MIN_SOURCE_DURATION_SECONDS}s"
            )
        return
    if not (MIN_SOURCE_DURATION_SECONDS <= duration <= MAX_SOURCE_DURATION_SECONDS):
        raise InbeidouError(
            f"源剧集时长不符合要求: {duration}s，要求 {MIN_SOURCE_DURATION_SECONDS}-{MAX_SOURCE_DURATION_SECONDS}s"
        )


def validate_promotion_constraints(platform: str, promotion: dict[str, Any] | None) -> None:
    normalized_platform = str(platform or "").strip().upper()
    info = dict(promotion or {})
    expected_platform_id = PUBLISH_TO_PROMOTION_PLATFORM.get(normalized_platform)
    link = str(info.get("promotion_link") or "").strip()
    if expected_platform_id and not link:
        raise InbeidouError(f"{normalized_platform} 发布缺少严格匹配的推广链接")

    actual_platform_id = info.get("promotion_platform_id")
    if expected_platform_id and actual_platform_id not in (None, ""):
        try:
            actual_platform_id_int = int(actual_platform_id)
        except (TypeError, ValueError):
            actual_platform_id_int = 0
        if actual_platform_id_int and actual_platform_id_int != expected_platform_id:
            raise InbeidouError(
                f"推广链接平台不匹配: 目标平台 {normalized_platform}，推广平台ID {actual_platform_id_int}"
            )

    if not link:
        return
    host = urlparse(link).netloc.lower()
    if not host:
        return
    for foreign_host in PLATFORM_HOST_CONFLICTS.get(normalized_platform, ()):
        if foreign_host in host:
            raise InbeidouError(f"推广链接疑似平台错配: {normalized_platform} 发布拿到了 {host} 链接")


def validate_publish_clip_constraints(clip: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = dict(clip or {})
    results: dict[str, dict[str, Any]] = {}
    for key, label in (
        ("downloaded_file", "剪辑成片"),
        ("publish_ready_file", "发布成片"),
    ):
        file_path = str(payload.get(key) or "").strip()
        if not file_path:
            continue
        path = Path(file_path).expanduser().resolve()
        if path.suffix.lower() != ".mp4":
            raise InbeidouError(f"{label}必须为 MP4 文件: {path.name}")
        meta_key = "downloaded_metadata" if key == "downloaded_file" else "publish_ready_metadata"
        meta = payload.get(meta_key) if isinstance(payload.get(meta_key), dict) else {}
        if not meta:
            meta = probe_video(str(path))
        file_size = _meta_int(meta, "file_size")
        if file_size > MAX_PUBLISH_FILE_SIZE_BYTES:
            raise InbeidouError(
                f"{label}大小超出限制: {round(file_size / 1024 / 1024, 2)}MB，要求不超过 400MB"
            )
        if key == "publish_ready_file":
            duration = _meta_int(meta, "file_duration")
            if duration > MAX_PUBLISH_DURATION_SECONDS:
                raise InbeidouError(
                    f"{label}时长超出限制: {duration}s，要求不超过 {MAX_PUBLISH_DURATION_SECONDS}s"
                )
            width = _meta_int(meta, "screen_x")
            height = _meta_int(meta, "screen_y")
            if width < MIN_PUBLISH_WIDTH or height < MIN_PUBLISH_HEIGHT:
                raise InbeidouError(
                    f"{label}分辨率过低: {width}x{height}，要求宽高至少 {MIN_PUBLISH_WIDTH}px"
                )
        results[meta_key] = dict(meta)
    return results
