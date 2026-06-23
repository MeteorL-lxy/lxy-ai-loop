#!/usr/bin/env python3
"""Resolve ai-loop root: vendor copy first, else AI_LOOP_ROOT / .env."""

from __future__ import annotations

import os
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def resolve_ai_loop_root() -> Path:
    vendor = PKG_ROOT / "vendor" / "ai-loop"
    if (vendor / "scripts" / "batch_tag_by_phones.py").is_file():
        return vendor

    env_path = PKG_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "AI_LOOP_ROOT" and v.strip():
                os.environ.setdefault("AI_LOOP_ROOT", v.strip())

    root = Path(os.environ.get("AI_LOOP_ROOT", r"d:\桌面文件\ai-loop")).resolve()
    if not (root / "scripts" / "batch_tag_by_phones.py").is_file():
        raise FileNotFoundError(
            f"ai-loop not found at {root}. Run: python scripts/sync_from_ai_loop.py"
        )
    return root
