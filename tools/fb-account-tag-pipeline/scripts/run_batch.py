#!/usr/bin/env python3
"""Run batch_tag_by_phones.py from standalone package."""

from __future__ import annotations

import os
import subprocess
import sys
import time
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


def normalize_outdir_args(argv: list[str]) -> list[str]:
    normalized: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--outdir" and index + 1 < len(argv):
            value = Path(argv[index + 1]).expanduser()
            normalized.extend([arg, str(value if value.is_absolute() else (PKG / value).resolve())])
            index += 2
            continue
        if arg.startswith("--outdir="):
            value = Path(arg.split("=", 1)[1]).expanduser()
            normalized.append(f"--outdir={value if value.is_absolute() else (PKG / value).resolve()}")
            index += 1
            continue
        normalized.append(arg)
        index += 1
    return normalized


def effective_outdir(default_outdir: Path, argv: list[str]) -> Path:
    outdir = default_outdir
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--outdir" and index + 1 < len(argv):
            outdir = Path(argv[index + 1]).expanduser()
            index += 2
            continue
        if arg.startswith("--outdir="):
            outdir = Path(arg.split("=", 1)[1]).expanduser()
        index += 1
    return outdir if outdir.is_absolute() else (PKG / outdir).resolve()


def organize_main_tables(outdir: Path) -> list[Path]:
    csv_dir = outdir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    for path in sorted(outdir.glob("*.csv")):
        name = path.name
        stem = path.stem
        if len(stem) != 8 or not stem.isdigit():
            continue
        target = csv_dir / name
        path.replace(target)
        moved.append(target)
    for path in sorted(outdir.glob("*_en.csv")):
        name = path.name
        stem = name[:-7]
        if len(stem) != 8 or not stem.isdigit():
            continue
        target = csv_dir / name
        path.replace(target)
    return moved


def latest_main_table(outdir: Path, *, started_at: float) -> Path | None:
    candidates: list[Path] = []
    for path in sorted((outdir / "csv").glob("*.csv")):
        stem = path.stem
        if len(stem) == 8 and stem.isdigit() and path.stat().st_mtime >= started_at - 2:
            candidates.append(path)
    if candidates:
        return max(candidates, key=lambda item: item.stat().st_mtime)
    return None


def main() -> int:
    load_dotenv()
    ai_loop = resolve_ai_loop_root()
    phones = PKG / "config" / "phones.txt"
    if not phones.is_file():
        phones = PKG / "config" / "phones.example.txt"

    code = os.environ.get("BEIDOU_LOGIN_CODE", "951103")
    lookback_days = os.environ.get("LOOKBACK_DAYS", "30")
    default_outdir = PKG / "runs" / "latest"
    extra_argv = normalize_outdir_args(list(sys.argv[1:]))
    if "--days" not in extra_argv:
        extra_argv = ["--days", lookback_days, *extra_argv]
    outdir = effective_outdir(default_outdir, extra_argv)
    outdir.mkdir(parents=True, exist_ok=True)
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
    started_at = time.time()
    exit_code = subprocess.call(cmd, cwd=str(ai_loop))
    organize_main_tables(outdir)
    main_table = latest_main_table(outdir, started_at=started_at)
    if main_table is not None:
        print("main_table:", main_table)
    else:
        print(f"main_table missing under {outdir / 'csv'}", file=sys.stderr)
    if exit_code == 0 and main_table is None:
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
