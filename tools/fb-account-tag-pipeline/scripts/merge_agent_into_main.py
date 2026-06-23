#!/usr/bin/env python3
"""Replace rows for one agent_id in main tag CSV, re-export EN CSV."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PKG / "scripts"))
from resolve_ai_loop_root import resolve_ai_loop_root  # noqa: E402


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"empty csv: {path}")
        return list(reader.fieldnames), list(reader)


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace agent rows in main merged tag CSV.")
    parser.add_argument("--main", required=True, help="Main YYYYMMDD.csv path")
    parser.add_argument("--patch", required=True, help="Rerun YYYYMMDD.csv path")
    parser.add_argument("--agent-id", required=True, help="agent_id to replace (e.g. 67020404)")
    parser.add_argument("--no-export-en", action="store_true", help="Skip export_account_tag_db.py")
    args = parser.parse_args()

    ai_loop = resolve_ai_loop_root()
    main_p = Path(args.main)
    patch_p = Path(args.patch)
    if not main_p.is_file():
        raise SystemExit(f"main not found: {main_p}")
    if not patch_p.is_file():
        raise SystemExit(f"patch not found: {patch_p}")

    cols, main_rows = read_rows(main_p)
    _, patch_rows = read_rows(patch_p)
    agent = str(args.agent_id).strip()

    kept = [r for r in main_rows if str(r.get("agent_id") or "").strip() != agent]
    patch_ok = [r for r in patch_rows if str(r.get("agent_id") or "").strip() == agent]
    merged = kept + patch_ok
    write_rows(main_p, cols, merged)

    print(f"removed agent {agent}: {len(main_rows) - len(kept)} rows")
    print(f"added patch: {len(patch_ok)} rows")
    print(f"merged total: {len(merged)} rows -> {main_p}")

    if not args.no_export_en:
        en_p = main_p.with_name(main_p.stem + "_en.csv")
        proc = subprocess.run(
            [
                sys.executable,
                str(ai_loop / "scripts" / "export_account_tag_db.py"),
                "--input",
                str(main_p.resolve()),
                "--out",
                str(en_p.resolve()),
            ],
            cwd=str(ai_loop),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout, file=sys.stderr)
            return proc.returncode
        print(proc.stdout.strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
