"""
Token estimation and usage calculation utilities
"""

import json
import re
from typing import Any, Dict

CHARS_PER_TOKEN = 4

# Per-character token cost by character class. Real BPE tokenizers (cl100k/o200k)
# treat ASCII densely (~4 chars/token) but tokenize Cyrillic and CJK far less
# efficiently. A flat len/4 heuristic underestimates Russian text by ~2x, which
# delays auto-compaction and understates context usage. These weights approximate
# cl100k_base ratios without pulling in a tokenizer dependency.
_TOKEN_COST_ASCII = 0.25  # ~4 chars/token
_TOKEN_COST_CYRILLIC = 0.5  # ~2 chars/token
_TOKEN_COST_CJK = 0.7  # ~1.4 chars/token
_TOKEN_COST_OTHER = 0.5  # other non-ASCII (latin-extended, emoji, etc.)

_RE_ASCII = re.compile(r"[\x00-\x7F]")
_RE_CYRILLIC = re.compile(r"[\u0400-\u04FF]")
_RE_CJK = re.compile(r"[\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]")


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    # Fast path: pure ASCII (code, JSON, English) keeps the classic 4 chars/token
    if text.isascii():
        return max(0, round(len(text) / CHARS_PER_TOKEN))

    ascii_n = sum(1 for _ in _RE_ASCII.finditer(text))
    cyrillic_n = sum(1 for _ in _RE_CYRILLIC.finditer(text))
    cjk_n = sum(1 for _ in _RE_CJK.finditer(text))
    other_n = len(text) - ascii_n - cyrillic_n - cjk_n

    cost = (
        ascii_n * _TOKEN_COST_ASCII
        + cyrillic_n * _TOKEN_COST_CYRILLIC
        + cjk_n * _TOKEN_COST_CJK
        + other_n * _TOKEN_COST_OTHER
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
