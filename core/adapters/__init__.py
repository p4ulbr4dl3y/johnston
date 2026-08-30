from typing import Dict

from core.adapters.anthropic import AnthropicAdapter, apply_anthropic_rolling_cache
from core.adapters.base import BaseApiAdapter, sort_keys_recursive
from core.adapters.gemini import GeminiAdapter
from core.adapters.openai import OpenAIAdapter, format_messages_for_openai

__all__ = [
    "ADAPTERS",
    "AnthropicAdapter",
    "BaseApiAdapter",
    "GeminiAdapter",
    "OpenAIAdapter",
    "apply_anthropic_rolling_cache",
    "format_messages_for_openai",
    "get_adapter",
    "sort_keys_recursive",
]


ADAPTERS: Dict[str, BaseApiAdapter] = {
    "openai": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
    "gemini": GeminiAdapter(),
}


def get_adapter(api_type: str = "openai") -> BaseApiAdapter:
    key = (api_type or "openai").lower().strip()
    if key not in ADAPTERS:
        raise ValueError(f"Unknown API adapter type: {api_type!r}")
    return ADAPTERS[key]
