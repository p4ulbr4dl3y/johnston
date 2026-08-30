"""Domain entity for Provider definition."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_CHUNK_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_RETRY_BACKOFF = 2.0
DEFAULT_MAX_RETRY_DELAY = 10.0


@dataclass
class ProviderDef:
    """Resolved provider definition domain entity."""

    key: str
    name: str = ""
    base_url: str = ""
    model: str = ""
    models: List[str] = field(default_factory=list)
    fetch_models: bool = True
    api_type: str = "openai"
    headers: Optional[Dict[str, str]] = None
    extra_body: Optional[Dict[str, Any]] = None
    reasoning_effort: Optional[str] = None
    chunk_timeout: float = DEFAULT_CHUNK_TIMEOUT
    max_tokens: Optional[int] = None
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY
    retry_backoff: float = DEFAULT_RETRY_BACKOFF
    max_retry_delay: float = DEFAULT_MAX_RETRY_DELAY
    enabled: bool = True
    api_key: str = ""
    requires_key: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the dict shape used by consumers."""
        return {
            "key": self.key,
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "models": list(self.models),
            "fetch_models": self.fetch_models,
            "api_type": self.api_type,
            "headers": self.headers,
            "extra_body": self.extra_body,
            "reasoning_effort": self.reasoning_effort,
            "chunk_timeout": self.chunk_timeout,
            "max_tokens": self.max_tokens,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "retry_backoff": self.retry_backoff,
            "max_retry_delay": self.max_retry_delay,
            "enabled": self.enabled,
            "requires_key": self.requires_key,
        }

    def models_fallback(self) -> List[str]:
        """Resolve the fallback model list (explicit models, else default model)."""
        return list(self.models) if self.models else ([self.model] if self.model else [])
