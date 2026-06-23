#!/usr/bin/env python3
"""Copy minimal ai-loop runtime into vendor/ai-loop for standalone use."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "ai-loop"

# 打标流水线依赖的目录/文件（相对 ai-loop 根）
SYNC_ITEMS = [
    "scripts",
    "skills/ai-publish",
    "skills/ai-cut-animation",
    "config/account_tags_defaults.json",
    "config/account_tags_manual.json",
    "config/fb-drama-team-ids.txt",
    "config/fb-novel-team-ids.txt",
    "config/fb-fixed-team-ids.txt",
]


def copy_item(src_root: Path, rel: str, dst_root: Path) -> None:
    src = src_root / rel
    dst = dst_root / rel
    if not src.exists():
        print(f"skip missing: {rel}")
        return
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"copied dir: {rel}")
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"copied file: {rel}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync ai-loop runtime into vendor/ai-loop")
    parser.add_argument(
        "--source",
        default=None,
        help="ai-loop repo root (default: AI_LOOP_ROOT env or d:/桌面文件/ai-loop)",
    )
    args = parser.parse_args()

    import os

    src_root = Path(
        args.source
        or os.environ.get("AI_LOOP_ROOT", "")
        or r"d:\桌面文件\ai-loop",
    ).resolve()
    if not (src_root / "scripts" / "batch_tag_by_phones.py").is_file():
        print(f"ai-loop not found at: {src_root}", file=sys.stderr)
        return 1

    if VENDOR.exists():
        shutil.rmtree(VENDOR)
    VENDOR.mkdir(parents=True)

    for rel in SYNC_ITEMS:
        copy_item(src_root, rel, VENDOR)

    marker = VENDOR / ".synced_from"
    marker.write_text(str(src_root) + "\n", encoding="utf-8")
    print(f"\nOK vendor -> {VENDOR}")
    print(f"source: {src_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
