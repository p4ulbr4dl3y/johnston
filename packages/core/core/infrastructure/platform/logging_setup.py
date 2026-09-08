"""Logging setup for Johnston.

Configures a rotating file handler under LOGS_DIR once per process.
UI/CLI modules should call setup_logging() during startup so the handler is
guaranteed to be installed before any record is emitted. Also performs a one-shot
cleanup of stale tool/task logs, silences chatty third-party loggers and installs
global exception hooks so uncaught errors (synchronous and asyncio) are persisted
to the log with their traceback instead of being silently dropped.
"""

import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

from core.infrastructure.platform.paths import LOGS_DIR, TEMP_IMAGES_DIR
from core.infrastructure.platform.platform_utils import IMAGE_EXTENSIONS, cleanup_dir_by_age

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

SNAPSHOT_EXTENSIONS = (".log", ".txt", ".md", ".json", ".html", ".xml", ".csv")

_configured = False
_excepthook_installed = False

# Crash records are emitted under their own (child) logger name so they are easy
# to filter, but they propagate to the root handler and land in johnston.log.
_CRASH_LOGGER_NAME = "johnston.crash"
_ORIGINAL_EXCEPTHOOK = sys.excepthook


def in_crash_logger() -> logging.Logger:
    """Return the dedicated logger used for uncaught-exception records."""
    return logging.getLogger(_CRASH_LOGGER_NAME)


def cleanup_logs(logs_dir: str = LOGS_DIR, max_age_days: Optional[int] = None) -> int:
    """Remove stale per-tool/task snapshot files under ``logs_dir``.

    Deletes snapshot files whose mtime is older than ``max_age_days``. The app
    log (``johnston.log``) and its rotations are always preserved: the rotating
    handler keeps an open handle, and unlinking it would silently drop new
    records (writes land in the unlinked inode). Returns the number of removed
    files. Never raises; individual failures are swallowed.
    """
    if max_age_days is None:
        try:
            from core.infrastructure.config.settings import get_settings

            max_age_days = get_settings().storage.max_log_age_days
        except Exception:
            max_age_days = MAX_LOG_AGE_DAYS

    return cleanup_dir_by_age(
        logs_dir,
        max_age_days=max_age_days,
        extensions=SNAPSHOT_EXTENSIONS,
        exclude_prefixes=("johnston.log",),
    )


def cleanup_temp_images(temp_images_dir: str = TEMP_IMAGES_DIR, max_age_days: Optional[int] = None) -> int:
    """Remove stale temporary/pasted image files under ``temp_images_dir``.

    Deletes image files whose mtime is older than ``max_age_days``. Returns the
    number of removed files. Never raises; individual failures are swallowed.
    """
    if max_age_days is None:
        try:
            from core.infrastructure.config.settings import get_settings

            max_age_days = get_settings().storage.max_log_age_days
        except Exception:
            max_age_days = MAX_LOG_AGE_DAYS

    return cleanup_dir_by_age(
        temp_images_dir,
        max_age_days=max_age_days,
        extensions=tuple(IMAGE_EXTENSIONS) + (".tmp",),
    )


def _quiet_noisy_loggers() -> None:
    for name in _NOISY_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.WARNING)


def _uncaught_exception_hook(exc_type, exc, tb) -> None:
    """sys.excepthook handler: persist uncaught synchronous exceptions.

    KeyboardInterrupt is passed on to the original hook so Ctrl+C still behaves
    as the interpreter expects; anything else is written to the crash logger with
    its full traceback.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        _ORIGINAL_EXCEPTHOOK(exc_type, exc, tb)
        return
    in_crash_logger().critical("Uncaught exception", exc_info=(exc_type, exc, tb))


def install_excepthook() -> None:
    """Route uncaught synchronous exceptions to the crash logger (idempotent)."""
    global _excepthook_installed
    if _excepthook_installed:
        return
    _excepthook_installed = True
    sys.excepthook = _uncaught_exception_hook


def _asyncio_exception_handler(loop, context) -> None:
    """asyncio loop exception handler: persist unhandled task failures.

    Replaces the default handler, which only emits a bare "Task exception was
    never retrieved" warning from a noisy third-party logger and drops the
    traceback. Kept at the child "johnston.crash" logger with the full stack.
    """
    message = context.get("message", "Unhandled exception in asyncio task")
    exc = context.get("exception")
    logger = in_crash_logger()
    if exc is not None:
        logger.critical("Unhandled exception in asyncio task: %s", message, exc_info=exc)
    else:
        logger.critical("Unhandled exception in asyncio task: %s", message)


def install_asyncio_exception_handler(loop: "asyncio.AbstractEventLoop | None" = None) -> None:
    """Route unhandled asyncio task failures to the crash logger.

    Call once the event loop is running (e.g. from a widget's ``on_mount``) so
    background-task failures are no longer lost. If ``loop`` is omitted the
    currently running loop is used; when none is running the call is a no-op.
    """
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
    loop.set_exception_handler(_asyncio_exception_handler)


def _log_task_done(task) -> None:
    """Done-callback that persists an unhandled asyncio task exception."""
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except (asyncio.CancelledError, Exception):
        return
    if exc is not None:
        in_crash_logger().critical("Background task failed", exc_info=exc)


def adopt_task_exception(task) -> None:
    """Ensure a fire-and-forget asyncio task logs its exception on failure.

    Without this, asyncio discards fire-and-forget task exceptions and only
    emits a bare "exception was never retrieved" warning lacking the stack.
    Attach via ``task.add_done_callback(adopt_task_exception)`` (or pass to
    ``adopt_task_exception`` after creation, which registers the callback).
    """
    if task is None:
        return
    task.add_done_callback(_log_task_done)


def setup_logging() -> None:
    """Install the rotating file handler on the root logger (idempotent)."""
    global _configured
    if _configured:
        return
    _configured = True
    os.makedirs(LOGS_DIR, exist_ok=True)
    try:
        from core.infrastructure.config.settings import get_settings

        max_bytes = get_settings().storage.max_log_bytes
    except Exception:
        max_bytes = _MAX_BYTES

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=max_bytes,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    cleanup_logs()
    cleanup_temp_images()
    _quiet_noisy_loggers()
    install_excepthook()
