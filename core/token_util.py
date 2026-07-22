"""
Token estimation and usage calculation utilities
"""
import json
from typing import Any, Dict

CHARS_PER_TOKEN = 4

def estimate_tokens(input_val: Any) -> int:
    """
    Estimate token count based on string length (4 chars per token).
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

    return max(0, round(len(text) / CHARS_PER_TOKEN))

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
