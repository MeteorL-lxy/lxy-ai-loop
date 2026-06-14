from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from inbeidou_cli import probe_video


def is_vertical_publish_ready(*, metadata: dict[str, Any], target_width: int, target_height: int) -> bool:
    width = int(metadata.get("screen_x") or 0)
    height = int(metadata.get("screen_y") or 0)
    if width <= 0 or height <= 0:
        return False
    return width * 16 == height * 9


def normalize_video_to_vertical(
    *,
    input_path: str | Path,
    output_path: str | Path | None = None,
    target_width: int = 720,
    target_height: int = 1280,
) -> dict[str, Any]:
    source_path = Path(input_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Video file does not exist: {source_path}")

    target_path = (
        Path(output_path).expanduser().resolve()
        if output_path
        else source_path.with_name(f"{source_path.stem}_{target_width}x{target_height}{source_path.suffix}")
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)

    source_meta = probe_video(source_path)
    filter_chain = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    )
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vf",
        filter_chain,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(target_path),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not installed, cannot normalize clip output") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(f"ffmpeg normalization failed: {stderr}") from exc

    normalized_meta = probe_video(target_path)
    return {
        "path": str(target_path),
        "target_width": target_width,
        "target_height": target_height,
        "target_aspect_ratio": "9:16",
        "source": source_meta,
        "normalized": normalized_meta,
        "normalized_needed": True,
    }


def ensure_vertical_publish_ready(
    *,
    input_path: str | Path,
    output_path: str | Path | None = None,
    target_width: int = 720,
    target_height: int = 1280,
) -> dict[str, Any]:
    source_path = Path(input_path).expanduser().resolve()
    source_meta = probe_video(source_path)
    if is_vertical_publish_ready(metadata=source_meta, target_width=target_width, target_height=target_height):
        return {
            "path": str(source_path),
            "target_width": target_width,
            "target_height": target_height,
            "target_aspect_ratio": "9:16",
            "source": source_meta,
            "normalized": source_meta,
            "normalized_needed": False,
        }
    return normalize_video_to_vertical(
        input_path=source_path,
        output_path=output_path,
        target_width=target_width,
        target_height=target_height,
    )
