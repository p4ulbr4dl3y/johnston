"""Tests for core.infrastructure.platform.logging_setup."""

import logging
import os
import time

from core.infrastructure.platform.logging_setup import _quiet_noisy_loggers, cleanup_logs


def touch(path: str, age_days: float) -> None:
    """Create an empty file with mtime set ``age_days`` in the past."""
    with open(path, "w", encoding="utf-8"):
        pass
    os.utime(path, (time.time() - age_days * 86400,) * 2)


def test_cleanup_logs_removes_only_stale_snapshots(tmp_path):
    stale = str(tmp_path / "web_fetch_aa11.log")
    fresh = str(tmp_path / "shell_bb22.log")
    johnston = str(tmp_path / "johnston.log")
    rotation = str(tmp_path / "johnston.log.1")
    touch(stale, age_days=30)
    touch(fresh, age_days=0)
    touch(johnston, age_days=30)  # stale but must survive (open handle)
    touch(rotation, age_days=30)

    removed = cleanup_logs(str(tmp_path), max_age_days=7)

    assert removed == 1
    assert not os.path.exists(stale)
    assert os.path.exists(fresh)
    assert os.path.exists(johnston)
    assert os.path.exists(rotation)


def test_cleanup_logs_missing_dir_returns_zero(tmp_path):
    assert cleanup_logs(str(tmp_path / "nope"), max_age_days=7) == 0


def test_cleanup_logs_ignores_non_log_files(tmp_path):
    other = tmp_path / "notes.txt"
    stale_log = tmp_path / "mcp_big_data_zz.log"
    touch(other, age_days=30)
    touch(stale_log, age_days=30)

    removed = cleanup_logs(str(tmp_path), max_age_days=7)

    assert removed == 1
    assert os.path.exists(other)
    assert not os.path.exists(stale_log)


def test_quiet_noisy_loggers_raises_level_to_warning():
    # Reset to a low level first to prove the function is what bumps it.
    for name in ("httpx", "openai", "urllib3"):
        logging.getLogger(name).setLevel(logging.DEBUG)

    _quiet_noisy_loggers()

    for name in ("httpx", "httpcore", "openai", "anthropic", "urllib3", "asyncio", "PIL"):
        assert logging.getLogger(name).level == logging.WARNING
