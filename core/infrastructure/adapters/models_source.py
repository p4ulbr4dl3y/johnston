"""External model-catalog wire sources and JSON-schema parsing.

Knowledge of external API wire formats (model catalog HTTP endpoints and the
shape of their JSON payloads) is infrastructure, not domain policy. The domain
policy stays pure math; this adapter owns the endpooint URLs and the
OpenRouter/models.dev response-field parsing.
"""

from typing import Optional

MODELS_DEV_URL = "https://models.dev/api.json"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


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
