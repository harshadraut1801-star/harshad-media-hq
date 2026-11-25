"""Logging setup: console + daily file in logs/. Never log secrets."""
from __future__ import annotations

import logging
from datetime import date

from .config import Settings
from .paths import safe_write_path

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(settings: Settings, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("hq")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console)
    log_file = safe_write_path(settings, settings.project_path("logs") / f"hq-{date.today():%Y-%m-%d}.log")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter(_FMT))
    logger.addHandler(fh)
    return logger
