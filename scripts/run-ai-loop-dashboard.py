from __future__ import annotations

import os
import runpy
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent

os.environ.setdefault("AI_LOOP_DASHBOARD_HOST", os.getenv("TEST_POOL_DASHBOARD_HOST", "127.0.0.1"))
os.environ.setdefault("AI_LOOP_DASHBOARD_PORT", os.getenv("TEST_POOL_DASHBOARD_PORT", "8765"))

runpy.run_path(str(ROOT_DIR / "scripts" / "run-test-pool-dashboard.py"), run_name="__main__")
