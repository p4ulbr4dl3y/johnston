"""Logging setup for Johnston.

Configures a rotating file handler under LOGS_DIR once per process.
UI/CLI modules should obtain loggers via get_logger() so the handler is
guaranteed to be installed before any record is emitted.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from core.config import LOGS_DIR

LOG_FILE = os.path.join(LOGS_DIR, "johnston.log")
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3

_configured = False


def setup_logging() -> None:
    """Install the rotating file handler on the root logger (idempotent)."""
    global _configured
    if _configured:
        return
    _configured = True
    os.makedirs(LOGS_DIR, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """Return a logger for ``name``, ensuring the file handler is installed."""
    setup_logging()
    return logging.getLogger(name)
