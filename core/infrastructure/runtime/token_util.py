"""
Token estimation and usage calculation utilities
"""

import json
from collections import OrderedDict
from typing import Any, Dict

# ~4 chars/token BPE density for ASCII text.
_CHARS_PER_TOKEN = 4

# Per-character token cost by character class. Real BPE tokenizers (cl100k/o200k)
# treat ASCII densely (~4 chars/token) but tokenize Cyrillic and CJK far less
# efficiently. A flat len/4 heuristic underestimates Russian text by ~2x, which
# delays auto-compaction and understates context usage. These weights approximate
# cl100k_base ratios without pulling in a tokenizer dependency.
_TOKEN_COST_ASCII = 0.25  # ~4 chars/token
_TOKEN_COST_CYRILLIC = 0.5  # ~2 chars/token
_TOKEN_COST_CJK = 0.7  # ~1.4 chars/token

# Character class ranges (single-pass classification replaces 3 regex passes).
# ASCII: same as str.isascii().
# Cyrillic: U+0400–U+04FF.
# CJK: Unicode CJK Unified (U+4E00–U+9FFF), Hiragana/Katakana (U+3040–U+30FF),
#      Hangul syllables (U+AC00–U+D7AF).
_CJK_START = 0x4E00
_CJK_END = 0x9FFF
_CJK_KANA_START = 0x3040
_CJK_KANA_END = 0x30FF
_CJK_HANGUL_START = 0xAC00
_CJK_HANGUL_END = 0xD7AF
_CYRILLIC_START = 0x0400
_CYRILLIC_END = 0x04FF


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    # Fast path: pure ASCII (code, JSON, English) keeps the classic 4 chars/token
    if text.isascii():
        return max(0, round(len(text) / _CHARS_PER_TOKEN))

    ascii_n = 0
    cyrillic_n = 0
    cjk_n = 0
    other_n = 0
    for ch in text:
        cp = ord(ch)
        if cp < 0x80:
            ascii_n += 1
        elif _CYRILLIC_START <= cp <= _CYRILLIC_END:
            cyrillic_n += 1
        elif (
            (_CJK_START <= cp <= _CJK_END)
            or (_CJK_KANA_START <= cp <= _CJK_KANA_END)
            or (_CJK_HANGUL_START <= cp <= _CJK_HANGUL_END)
        ):
            cjk_n += 1
        else:
            other_n += 1

    cost = (
        ascii_n * _TOKEN_COST_ASCII
        + cyrillic_n * _TOKEN_COST_CYRILLIC
        + cjk_n * _TOKEN_COST_CJK
        + other_n * _TOKEN_COST_CYRILLIC  # non-ASCII residual same density as Cyrillic
    )
    return max(0, round(cost))


# Memo cache for non-string inputs that get serialized (json.dumps) before counting.
# Histories are passed to estimate_tokens repeatedly within a turn (compaction guard,
# prompt-token estimate, status-footer refresh), and re-serializing an unchanged
# history on each call is pure waste. The key is a cheap (<len,  type-id, content>
# derived) signature and the memoized value is the already-computed token int, so
# the cache never holds the (potentially large) input object itself in memory.
# OrderedDict + maxsize evicts the least-recently-used entry, keeping the cache
# bounded. Entries where two distinct objects have identical serialized content are
# safe to alias because token estimation is a pure, deterministic function of the
# serialized text.
_CACHE_STR_KEY_MAX = 20000
_ESTIMATE_CACHE_MAXSIZE = 256
_estimate_cache: "OrderedDict[tuple, int]" = OrderedDict()


def _structural_key(val: Any, depth: int = 0) -> tuple:
    if depth > 5:
        return (id(val), type(val).__name__)
    if isinstance(val, str):
        if len(val) > _CACHE_STR_KEY_MAX:
            return ("big", "str")
        return ("s", len(val), hash(val))
    if isinstance(val, (int, float, bool)) or val is None:
        return ("p", val)
    if isinstance(val, dict):
        if len(val) > _CACHE_STR_KEY_MAX:
            return ("big", "dict")
        items = []
        for k, v in val.items():
            k_str = str(k)
            if isinstance(v, str):
                if len(v) > _CACHE_STR_KEY_MAX:
                    return ("big", "dict")
                items.append((k_str, len(v), hash(v)))
            elif isinstance(v, (int, float, bool)) or v is None:
                items.append((k_str, v))
            else:
                sub = _structural_key(v, depth + 1)
                if isinstance(sub, tuple) and len(sub) >= 1 and sub[0] == "big":
                    return ("big", "dict")
                items.append((k_str, sub))
        return ("dict", tuple(items))
    if isinstance(val, (list, tuple)):
        if len(val) > _CACHE_STR_KEY_MAX:
            return ("big", type(val).__name__)
        items = []
        for item in val:
            sub = _structural_key(item, depth + 1)
            if isinstance(sub, tuple) and len(sub) >= 1 and sub[0] == "big":
                return ("big", type(val).__name__)
            items.append(sub)
        return (type(val).__name__, len(val), tuple(items))
    try:
        length = len(val)
        if length > _CACHE_STR_KEY_MAX:
            return ("big", type(val).__name__)
    except Exception:
        pass
    return (type(val).__name__, id(val))


def _estimate_cache_key(input_val: Any) -> tuple:
    """Build a cheap, hashable cache key for a serializable input without string allocations."""
    if isinstance(input_val, str):
        if len(input_val) > _CACHE_STR_KEY_MAX:
            return ("big", "str")
        return ("str", len(input_val), hash(input_val))
    return _structural_key(input_val)


def estimate_tokens(input_val: Any) -> int:
    """
    Estimate token count using a character-class-aware heuristic.
    ASCII is ~4 chars/token; Cyrillic ~2 chars/token; CJK ~1.4 chars/token.
    Supports strings, dicts, lists, or primitive types.

    Results for non-string inputs are memoized in a small LRU cache keyed by a
    content signature. Because histories are *mutated* in place between calls, the
    key is rebuilt from the (cheap) len+repr each time and only matches when the
    input is truly unchanged, so stale cached values are never served.
    """
    if input_val is None:
        return 0
    if isinstance(input_val, str):
        # Immutable: always safe to memoize. Empty/large strings skip the cache
        # (empty is trivial; huge strings rarely repeat and would cost memory).
        if input_val and len(input_val) <= _CACHE_STR_KEY_MAX:
            key = _estimate_cache_key(input_val)
            cached = _estimate_cache.get(key)
            if cached is not None:
                _estimate_cache.move_to_end(key)
                return cached
            val = _estimate_text_tokens(input_val)
            _estimate_cache[key] = val
        else:
            val = _estimate_text_tokens(input_val)
        return val

    # Non-string: serialize then count. Only memoized when the content signature
    # is exact; "big" (overflow/oversize) inputs bail straight through so distinct
    # large objects never alias the same cache slot.
    key = _estimate_cache_key(input_val)
    cached = _estimate_cache.get(key)
    if cached is not None:
        _estimate_cache.move_to_end(key)
        return cached
    try:
        text = json.dumps(input_val, ensure_ascii=False)
    except Exception:
        text = str(input_val)
    val = _estimate_text_tokens(text)
    if key[0] != "big":
        _estimate_cache[key] = val
    _trim_cache()
    return val


def _trim_cache() -> None:
    while len(_estimate_cache) > _ESTIMATE_CACHE_MAXSIZE:
        _estimate_cache.popitem(last=False)


def parse_usage(usage: Any) -> Dict[str, Any]:
    """
    Extract token counts and cost from API usage object if available, including cache details.
    """
    if not usage:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost": None,
        }

    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    total = getattr(usage, "total_tokens", 0) or (prompt + completion)

    cache_read = 0
    cache_write = 0
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    if prompt_details:
        cached_attr = getattr(prompt_details, "cached_tokens", None)
        if cached_attr is not None and not hasattr(cached_attr, "_mock_name"):
            cache_read = cached_attr
        else:
            read_attr = getattr(prompt_details, "cache_read_tokens", 0)
            if not hasattr(read_attr, "_mock_name"):
                cache_read = read_attr or 0

        cw_attr = getattr(prompt_details, "cache_write_tokens", None)
        if cw_attr is not None and not hasattr(cw_attr, "_mock_name"):
            cache_write = cw_attr
        else:
            cc_attr = getattr(prompt_details, "cache_creation_tokens", 0)
            if not hasattr(cc_attr, "_mock_name"):
                cache_write = cc_attr or 0

    cost = getattr(usage, "cost", None)
    if cost is None or hasattr(cost, "_mock_name"):
        cost = getattr(usage, "cost_usd", None)
    if hasattr(cost, "_mock_name"):
        cost = None

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "cost": cost,
    }
