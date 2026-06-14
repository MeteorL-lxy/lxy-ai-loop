from __future__ import annotations

import logging
from pathlib import Path


def setup_round_logger(logs_dir: Path, round_id: int) -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"flywheel.round.{round_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_path = logs_dir / f"round_{round_id}.log"
    if not any(
        isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_path
        for handler in logger.handlers
    ):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)

    return logger

