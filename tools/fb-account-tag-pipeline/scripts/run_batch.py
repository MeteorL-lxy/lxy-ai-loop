#!/usr/bin/env python3
"""Run batch_tag_by_phones.py from standalone package."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "scripts"))
from resolve_ai_loop_root import resolve_ai_loop_root  # noqa: E402


def load_dotenv() -> None:
    env_file = PKG / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_dotenv()
    ai_loop = resolve_ai_loop_root()
    phones = PKG / "config" / "phones.txt"
    if not phones.is_file():
        phones = PKG / "config" / "phones.example.txt"

    outdir = PKG / "runs" / "latest"
    outdir.mkdir(parents=True, exist_ok=True)

    code = os.environ.get("BEIDOU_LOGIN_CODE", "951103")
    lookback_days = os.environ.get("LOOKBACK_DAYS", "30")
    extra_argv = list(sys.argv[1:])
    if "--days" not in extra_argv:
        extra_argv = ["--days", lookback_days, *extra_argv]
    cmd = [
        sys.executable,
        str(ai_loop / "scripts" / "batch_tag_by_phones.py"),
        "--phones",
        str(phones.resolve()),
        "--code",
        code,
        "--outdir",
        str(outdir.resolve()),
        "--skip-apify",
        "--skip-db-import",
        *extra_argv,
    ]
    print("ai-loop:", ai_loop)
    print("cmd:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ai_loop))


if __name__ == "__main__":
    raise SystemExit(main())
