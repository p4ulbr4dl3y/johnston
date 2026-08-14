"""
Token estimation and usage calculation utilities
"""

import json
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


def estimate_tokens(input_val: Any) -> int:
    """
    Estimate token count using a character-class-aware heuristic.
    ASCII is ~4 chars/token; Cyrillic ~2 chars/token; CJK ~1.4 chars/token.
    Supports strings, dicts, lists, or primitive types.
    """
    if input_val is None:
        return 0
    if not isinstance(input_val, str):
        try:
            text = json.dumps(input_val, ensure_ascii=False)
        except Exception:
            text = str(input_val)
    else:
        text = input_val

    return _estimate_text_tokens(text)


def parse_usage(usage: Any) -> Dict[str, int]:
    """
    Extract token counts from API usage object if available, including cache details.
    """
    if not usage:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0}

    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    total = getattr(usage, "total_tokens", 0) or (prompt + completion)

    cache_read = 0
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    if prompt_details:
        cache_read = getattr(prompt_details, "cached_tokens", 0) or 0

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cache_read_tokens": cache_read,
    }
