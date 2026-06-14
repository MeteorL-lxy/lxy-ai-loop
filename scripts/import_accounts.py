#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python3 scripts/import_accounts.py /path/to/accounts.csv")
    root = Path(__file__).resolve().parents[1]
    cli_path = root / "backend" / "flywheel_cli.py"
    command = [sys.executable, str(cli_path), "import-accounts", "--csv", sys.argv[1]]
    raise SystemExit(subprocess.call(command, cwd=root))


if __name__ == "__main__":
    main()
