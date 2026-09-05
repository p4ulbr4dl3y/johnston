import os
import time
from typing import Any, Tuple

from core.infrastructure.runtime.lru import LruCache

MAX_DOC_CACHE = 50
DOC_CACHE_TTL = 600.0  # 10 minutes
MAX_LINE_COUNT_CACHE = 500

_DOC_CACHE: "LruCache[str, Tuple[float, float, str]]" = LruCache(MAX_DOC_CACHE)  # key: path, val: (mtime, timestamp, md_text)
_LINE_COUNT_CACHE: "LruCache[Tuple[str, float, int], int]" = LruCache(MAX_LINE_COUNT_CACHE)


def _tools_settings() -> Any:
    """Return the tools config, falling back to module defaults on any failure."""
    try:
        from core.infrastructure.config.settings import get_settings

        return get_settings().tools
    except Exception:
        return None


def _get_file_line_count(file_path: str, mtime: float, size: int) -> int:
    key = (file_path, mtime, size)
    cached = _LINE_COUNT_CACHE.get(key)
    if cached is not None:
        return cached

    total = 0
    last_byte = b""
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                total += chunk.count(b"\n")
                last_byte = chunk[-1:]
        if last_byte and last_byte not in (b"\n", b"\r"):
            total += 1
    except Exception:
        return 0

    tools = _tools_settings()
    line_cap = tools.line_count_cache_max if tools else MAX_LINE_COUNT_CACHE
    _LINE_COUNT_CACHE.maxsize = line_cap
    _LINE_COUNT_CACHE.put(key, total)
    return total


def get_cached_doc_markdown(path: str) -> str | None:
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return None

    tools = _tools_settings()
    doc_ttl = tools.doc_cache_ttl if tools else DOC_CACHE_TTL
    cached = _DOC_CACHE.get(path)
    if cached is not None:
        cached_mtime, cached_ts, text = cached
        if cached_mtime == mtime and (time.monotonic() - cached_ts < doc_ttl):
            return text
        del _DOC_CACHE[path]
    return None


def set_cached_doc_markdown(path: str, text: str) -> None:
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return

    tools = _tools_settings()
    doc_cap = tools.max_doc_cache if tools else MAX_DOC_CACHE
    _DOC_CACHE.maxsize = doc_cap
    _DOC_CACHE.put(path, (mtime, time.monotonic(), text))
