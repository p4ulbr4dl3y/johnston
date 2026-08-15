"""
Pure helpers and constants for the AI model catalog.

Kept free of IO (no httpx, no disk cache) and free of singleton state for
easy reuse and testing.
"""

import re
from typing import Optional

MODELS_DEV_URL = "https://models.dev/api.json"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Precompiled regexes (avoids recompilation on every matching call).
_RE_FUZZY_STRIP = re.compile(r"(?i)[-_](mlx|4bit|8bit|16bit|gguf|q\d_[k0-9_]+|fp\d+|instruct|it|v\d+[\d\.]*)")
_RE_TOKEN_SPLIT = re.compile(r"[a-z0-9]+")


def extract_context_length(model: dict) -> Optional[int]:
    """Extracts context length from an OpenRouter model dict.

    Consolidates the source fields across OpenRouter API responses
    (context_length, top_provider.context_length, context_window,
    max_context_length). Returns int, or None when absent/invalid.
    """
    ctx = (
        model.get("context_length")
        or (model.get("top_provider", {}) or {}).get("context_length")
        or model.get("context_window")
        or model.get("max_context_length")
    )
    if ctx and isinstance(ctx, (int, float)):
        return int(ctx)
    return None


def format_context_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        val = tokens / 1_000_000
        if val % 1 == 0:
            return f"{int(val)}M"
        if round(val, 1) == 1.0:
            return "1M"
        return f"{val:.1f}M"
    elif tokens >= 1_000:
        val = tokens / 1_000
        if val >= 100 or val % 1 == 0:
            return f"{int(val)}k"
        return f"{val:.1f}k"
    return str(tokens)
