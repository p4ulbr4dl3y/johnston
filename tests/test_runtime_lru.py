"""Unit tests for the shared bounded LRU cache."""

import pytest

from core.infrastructure.runtime.lru import LruCache


def test_put_get_roundtrip():
    cache = LruCache(maxsize=3)
    cache.put("a", 1)
    assert cache.get("a") == 1
    assert cache.get("a", 99) == 1


def test_get_missing_returns_default():
    cache = LruCache(maxsize=3)
    assert cache.get("missing") is None
    assert cache.get("missing", 7) == 7


def test_put_updates_value():
    cache = LruCache(maxsize=3)
    cache.put("a", 1)
    cache.put("a", 2)
    assert cache.get("a") == 2
    assert len(cache) == 1


def test_eviction_by_limit():
    cache = LruCache(maxsize=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)  # evicts "a"
    assert "a" not in cache
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_promotion_keeps_recently_used():
    cache = LruCache(maxsize=3)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    # Touch "a" so it becomes most-recently-used.
    assert cache.get("a") == 1
    cache.put("d", 4)  # evicts "b" (least-recently-used), not "a"
    assert "a" in cache
    assert "b" not in cache
    assert cache.get("a") == 1
    assert cache.get("d") == 4


def test_contains_len_clear():
    cache = LruCache(maxsize=3)
    assert len(cache) == 0
    assert "x" not in cache
    cache.put("x", 1)
    cache.put("y", 2)
    assert "x" in cache
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0
    assert "x" not in cache
    assert cache.get("x") is None


def test_zero_maxsize_rejected():
    with pytest.raises(ValueError):
        LruCache(maxsize=0)
