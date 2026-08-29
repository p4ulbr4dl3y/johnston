"""Tests for core.infrastructure.platform.logging_setup."""

import asyncio
import logging
import os
import sys
import time

from core.infrastructure.platform.logging_setup import (
    _asyncio_exception_handler,
    _log_task_done,
    _quiet_noisy_loggers,
    _uncaught_exception_hook,
    adopt_task_exception,
    cleanup_logs,
    cleanup_temp_images,
    install_asyncio_exception_handler,
    install_excepthook,
)


def touch(path: str, age_days: float) -> None:
    """Create an empty file with mtime set ``age_days`` in the past."""
    with open(path, "w", encoding="utf-8"):
        pass
    os.utime(path, (time.time() - age_days * 86400,) * 2)


def test_cleanup_logs_removes_only_stale_snapshots(tmp_path):
    stale_log = str(tmp_path / "shell_aa11.log")
    stale_md = str(tmp_path / "web_fetch_aa11.md")
    stale_json = str(tmp_path / "mcp_bb22.json")
    fresh = str(tmp_path / "shell_bb22.log")
    johnston = str(tmp_path / "johnston.log")
    rotation = str(tmp_path / "johnston.log.1")
    touch(stale_log, age_days=30)
    touch(stale_md, age_days=30)
    touch(stale_json, age_days=30)
    touch(fresh, age_days=0)
    touch(johnston, age_days=30)  # stale but must survive (open handle)
    touch(rotation, age_days=30)

    removed = cleanup_logs(str(tmp_path), max_age_days=7)

    assert removed == 3
    assert not os.path.exists(stale_log)
    assert not os.path.exists(stale_md)
    assert not os.path.exists(stale_json)
    assert os.path.exists(fresh)
    assert os.path.exists(johnston)
    assert os.path.exists(rotation)


def test_cleanup_logs_missing_dir_returns_zero(tmp_path):
    assert cleanup_logs(str(tmp_path / "nope"), max_age_days=7) == 0


def test_cleanup_logs_ignores_non_snapshot_files(tmp_path):
    other = tmp_path / "notes.bin"
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


# --- uncaught-exception / crash logging -------------------------------------


def test_install_excepthook_registers_and_is_idempotent():
    import core.infrastructure.platform.logging_setup as ls

    original_hook = sys.excepthook
    ls._excepthook_installed = False
    try:
        install_excepthook()
        assert sys.excepthook is ls._uncaught_exception_hook

        # Second call must not re-register (idempotent).
        install_excepthook()
        assert sys.excepthook is ls._uncaught_exception_hook
    finally:
        sys.excepthook = original_hook
        ls._excepthook_installed = False


def test_uncaught_exception_hook_logs_critical(caplog):
    with caplog.at_level(logging.CRITICAL, logger="johnston.crash"):
        _uncaught_exception_hook(ValueError, ValueError("boom"), None)
    recs = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert recs and "Uncaught exception" in recs[0].message
    assert recs[0].exc_info is not None


def test_uncaught_exception_hook_forwards_keyboard_interrupt(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "core.infrastructure.platform.logging_setup._ORIGINAL_EXCEPTHOOK",
        lambda t, v, tb: captured.append(t),
    )
    _uncaught_exception_hook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert captured == [KeyboardInterrupt]


def test_asyncio_exception_handler_logs_critical_with_exception(caplog):
    context = {"message": "Task failed", "exception": RuntimeError("boom")}
    with caplog.at_level(logging.CRITICAL, logger="johnston.crash"):
        _asyncio_exception_handler(None, context)
    recs = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert recs and "Unhandled exception in asyncio task" in recs[0].message


def test_asyncio_exception_handler_logs_message_without_exception(caplog):
    context = {"message": "Task failed"}
    with caplog.at_level(logging.CRITICAL, logger="johnston.crash"):
        _asyncio_exception_handler(None, context)
    recs = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert recs and "Unhandled exception in asyncio task" in recs[0].message


def test_install_asyncio_exception_handler_sets_handler():
    loop = asyncio.new_event_loop()
    try:
        install_asyncio_exception_handler(loop)
        assert loop.get_exception_handler() is _asyncio_exception_handler
    finally:
        loop.close()


def test_install_asyncio_exception_handler_noop_without_loop():
    # No running loop -> must be a safe no-op, not raise.
    install_asyncio_exception_handler(None)


def test_adopt_task_exception_logs_unhandled_failure(caplog):
    loop = asyncio.new_event_loop()
    try:
        async def fail():
            await asyncio.sleep(0)
            raise RuntimeError("boom")

        task = loop.create_task(fail())
        adopt_task_exception(task)
        with caplog.at_level(logging.CRITICAL, logger="johnston.crash"):
            loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        recs = [r for r in caplog.records if r.levelno == logging.CRITICAL]
        assert recs and "Background task failed" in recs[0].message
    finally:
        loop.close()


def test_log_task_done_skips_successful_task():
    loop = asyncio.new_event_loop()
    try:
        async def ok():
            return 1

        task = loop.create_task(ok())
        loop.run_until_complete(task)
        # A successfully-completed task must not raise when inspected.
        _log_task_done(task)
    finally:
        loop.close()


def test_cleanup_temp_images_removes_stale_images_and_tmp(tmp_path):
    stale_png = str(tmp_path / "pasted_image_old.png")
    stale_jpg = str(tmp_path / "clip_old.jpg")
    stale_tmp = str(tmp_path / "raw_clip_123.tmp")
    fresh_png = str(tmp_path / "pasted_image_new.png")
    non_image = str(tmp_path / "keep_me.txt")

    touch(stale_png, age_days=10)
    touch(stale_jpg, age_days=10)
    touch(stale_tmp, age_days=10)
    touch(fresh_png, age_days=0)
    touch(non_image, age_days=10)

    removed = cleanup_temp_images(str(tmp_path), max_age_days=7)

    assert removed == 3
    assert not os.path.exists(stale_png)
    assert not os.path.exists(stale_jpg)
    assert not os.path.exists(stale_tmp)
    assert os.path.exists(fresh_png)
    assert os.path.exists(non_image)


def test_cleanup_temp_images_default_settings(tmp_path, monkeypatch):
    stale_png = str(tmp_path / "pasted.png")
    touch(stale_png, age_days=10)

    removed = cleanup_temp_images(str(tmp_path), max_age_days=None)
    assert removed == 1
    assert not os.path.exists(stale_png)

