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


def extract_provider_def(prov_key: str, prov_info: dict) -> Optional[dict]:
    """Extracts a Johnston-compatible Provider definition from a models.dev provider entry."""
    if not isinstance(prov_info, dict):
        return None
    name = prov_info.get("name") or prov_key
    api_url = prov_info.get("api") or ""
    npm = str(prov_info.get("npm") or "")

    if npm == "@ai-sdk/anthropic" or prov_key == "anthropic":
        api_type = "anthropic"
        if not api_url:
            api_url = "https://api.anthropic.com/v1"
    elif npm == "@ai-sdk/google" or "gemini" in prov_key or "google" in prov_key:
        api_type = "gemini"
        if not api_url:
            api_url = "https://generativelanguage.googleapis.com/v1beta"
    else:
        api_type = "openai"
        if not api_url and prov_key == "openai":
            api_url = "https://api.openai.com/v1"

    models_dict = prov_info.get("models", {})
    models_list = list(models_dict.keys()) if isinstance(models_dict, dict) else []

    requires_key = True
    if prov_key in ("lmstudio", "ollama", "litellm"):
        requires_key = False

    return {
        "key": prov_key,
        "name": name,
        "base_url": api_url,
        "api_type": api_type,
        "models": models_list,
        "fetch_models": True,
        "requires_key": requires_key,
    }

