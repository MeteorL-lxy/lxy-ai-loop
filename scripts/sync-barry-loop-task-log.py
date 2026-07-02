#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from loop_task_log_sync import main


if __name__ == "__main__":
    raise SystemExit(main())
