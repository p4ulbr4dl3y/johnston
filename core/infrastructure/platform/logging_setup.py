"""Logging setup for Johnston.

Configures a rotating file handler under LOGS_DIR once per process.
UI/CLI modules should call setup_logging() during startup so the handler is
guaranteed to be installed before any record is emitted. Also performs a one-shot
cleanup of stale tool/task logs and silences chatty third-party loggers.
"""

import logging
import os
import time
from logging.handlers import RotatingFileHandler

from core.infrastructure.platform.paths import LOGS_DIR

LOG_FILE = os.path.join(LOGS_DIR, "johnston.log")
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3

# Logs older than this are removed by cleanup_logs(). The app log and its
# rotations are always kept; only per-tool/task snapshot logs expire.
MAX_LOG_AGE_DAYS = 7

# Third-party loggers that spam INFO lines (HTTP requests, retries, progress).
# Raised to WARNING so johnston.log stays focused on our own diagnostics.
_NOISY_LOGGER_NAMES = (
    "httpx",
    "httpcore",
    "openai",
    "anthropic",
    "urllib3",
    "asyncio",
    "PIL",
)

_configured = False


def cleanup_logs(logs_dir: str = LOGS_DIR, max_age_days: int = MAX_LOG_AGE_DAYS) -> int:
    """Remove stale per-tool/task log files under ``logs_dir``.

    Deletes ``*.log`` files whose mtime is older than ``max_age_days``. The app
    log (``johnston.log``) and its rotations are always preserved: the rotating
    handler keeps an open handle, and unlinking it would silently drop new
    records (writes land in the unlinked inode). Returns the number of removed
    files. Never raises; individual failures are swallowed.
    """
    if not os.path.isdir(logs_dir):
        return 0
    cutoff = time.time() - max_age_days * 24 * 3600
    removed = 0
    for name in os.listdir(logs_dir):
        if not name.endswith(".log") or name.startswith("johnston.log"):
            continue
        path = os.path.join(logs_dir, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            continue
    return removed


def _quiet_noisy_loggers() -> None:
    for name in _NOISY_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.WARNING)


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
    cleanup_logs()
    _quiet_noisy_loggers()
