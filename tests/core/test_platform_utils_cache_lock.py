"""Regression tests for bounded JSON read cache and lock backoff in platform_utils."""

import json
import os

import pytest

from johnston.core.infrastructure.platform.platform_utils import (
    _JSON_READ_CACHE_MAX_SIZE,
    _json_read_cache,
    cached_json_read,
    interprocess_file_lock,
)

fcntl = pytest.importorskip("fcntl")


def test_json_read_cache_is_bounded_lru(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "johnston.core.infrastructure.platform.platform_utils._JSON_READ_CACHE_MAX_SIZE",
        4,
    )
    paths = []
    for i in range(7):
        path = str(tmp_path / f"c{i}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"i": i}))
        paths.append(path)

    assert cached_json_read(paths[0], {}) == {"i": 0}
    for path in paths[1:5]:
        assert cached_json_read(path, {}) == json.loads(open(path).read())
    # cap=4: inserting i0..i4 fills the cache, i4 evicts i0.
    assert len(_json_read_cache) == 4
    assert paths[0] not in _json_read_cache

    # A hit refreshes recency: re-reading c2 moves it to the end, so the next
    # insertion evicts c1 instead.
    assert cached_json_read(paths[2], {}) == {"i": 2}
    assert cached_json_read(paths[6], {}) == {"i": 6}
    assert len(_json_read_cache) == 4
    assert list(_json_read_cache) == [paths[3], paths[4], paths[2], paths[6]]

    assert cached_json_read(paths[0], {}) == {"i": 0}  # evicted entry re-reads fine
    assert len(_json_read_cache) == 4


def test_json_read_cache_replaces_on_mtime_change(tmp_path):
    path = str(tmp_path / "cfg.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"v": 1}))

    assert cached_json_read(path, {}) == {"v": 1}
    # Rewrite with same size but bumped mtime: entry must be replaced, not stacked.
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"v": 2}))
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    assert cached_json_read(path, {}) == {"v": 2}
    assert len(_json_read_cache) == 1


def test_interprocess_file_lock_acquires_and_releases(tmp_path):
    lock_path = str(tmp_path / "lock")

    with interprocess_file_lock(lock_path, timeout=1.0):
        # Re-entering must fail while the lock is held (same-process new fd).
        fd = os.open(lock_path, os.O_RDWR)
        try:
            with pytest.raises((BlockingIOError, OSError)):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    # Released after the context exits: a second acquisition succeeds.
    with interprocess_file_lock(lock_path, timeout=1.0):
        pass


def test_interprocess_file_lock_backoff_and_timeout(tmp_path, monkeypatch):
    lock_path = str(tmp_path / "lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        sleeps: list[float] = []
        clock = [0.0]
        monkeypatch.setattr(
            "johnston.core.infrastructure.platform.platform_utils.time.sleep",
            lambda delay: (sleeps.append(delay), clock.__setitem__(0, clock[0] + delay)),
        )
        monkeypatch.setattr(
            "johnston.core.infrastructure.platform.platform_utils.time.time",
            lambda: clock[0],
        )

        body_ran = False
        # Timeout contract preserved: the context manager yields (no exception),
        # then gives up on the lock instead of raising.
        with interprocess_file_lock(lock_path, timeout=0.1):
            body_ran = True

        assert body_ran
        assert sleeps, "backoff should have slept while the lock was contended"
        # Exponential backoff starting at 0.005s: each delay doubles the previous.
        assert sleeps[0] == 0.005
        assert all(b == pytest.approx(a * 2) for a, b in zip(sleeps, sleeps[1:]))
        assert max(sleeps) <= 0.25
        # Fixed 10ms busy-wait would produce uniform delays; backoff must not.
        assert len(set(sleeps)) > 1
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def test_json_read_cache_constant_exists():
    assert isinstance(_JSON_READ_CACHE_MAX_SIZE, int) and _JSON_READ_CACHE_MAX_SIZE > 0
