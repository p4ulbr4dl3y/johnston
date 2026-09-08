import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.domain.defaults.config import (
    DEFAULT_CHUNK_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_RETRY_DELAY,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_DELAY,
)

logger = logging.getLogger(__name__)


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

    @classmethod
    def from_dict(
        cls, key: str, data: Dict[str, Any], *, enabled: Optional[bool] = None
    ) -> "ProviderDef":
        """Build a ProviderDef from a raw provider JSON dict, applying defaults and secrets interpolation."""
        from core.infrastructure.secrets import interpolate_secrets, interpolate_secrets_in_obj

        raw_key = data.get("api_key") or ""
        resolved_key = interpolate_secrets(raw_key) if raw_key else ""
        raw_base_url = resolve_base_url_placeholders(data.get("base_url") or "", key, data)
        resolved_base_url = interpolate_secrets(raw_base_url)
        headers = interpolate_secrets_in_obj(data.get("headers")) if data.get("headers") else None

        try:
            from core.infrastructure.config.settings import get_settings

            llm_settings = get_settings().llm
            def_chunk_timeout = llm_settings.chunk_timeout
            def_max_retries = llm_settings.max_retries
            def_retry_delay = llm_settings.retry_delay
            def_retry_backoff = llm_settings.retry_backoff
            def_max_retry_delay = llm_settings.max_retry_delay
        except Exception:
            def_chunk_timeout = DEFAULT_CHUNK_TIMEOUT
            def_max_retries = DEFAULT_MAX_RETRIES
            def_retry_delay = DEFAULT_RETRY_DELAY
            def_retry_backoff = DEFAULT_RETRY_BACKOFF
            def_max_retry_delay = DEFAULT_MAX_RETRY_DELAY

        is_enabled = bool(data.get("enabled", True)) if enabled is None else enabled
        return cls(
            key=key,
            name=data.get("name") or key,
            base_url=resolved_base_url,
            model=data.get("model") or "",
            models=list(data.get("models") or []),
            fetch_models=bool(data.get("fetch_models", True)),
            api_type=data.get("api_type") or "openai",
            headers=headers,
            extra_body=data.get("extra_body"),
            reasoning_effort=data.get("reasoning_effort"),
            chunk_timeout=_field_float(data, "chunk_timeout", def_chunk_timeout),
            max_tokens=data.get("max_tokens"),
            max_retries=_field_int(data, "max_retries", def_max_retries),
            retry_delay=_field_float(data, "retry_delay", def_retry_delay),
            retry_backoff=_field_float(data, "retry_backoff", def_retry_backoff),
            max_retry_delay=_field_float(data, "max_retry_delay", def_max_retry_delay),
            enabled=is_enabled,
            api_key=resolved_key,
            requires_key=data.get("requires_key"),
        )


_BASE_URL_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_-]+)\}")
_WARNED_BASE_URL_TOKENS: set[tuple[str, str]] = set()


def resolve_base_url_placeholders(raw: str, provider_key: str, data: Dict[str, Any]) -> str:
    """Expand ``{token}`` placeholders in a base_url template (azure
    ``{resource}``, cloudflare ``{account_id}``, ...).

    Resolution order: ``<PROVIDER>_<TOKEN>`` env var, plain ``<TOKEN>`` env
    var, then a same-named string field of the provider definition.
    Unresolved tokens stay verbatim (visible failure, no silently wrong host)
    with a one-time warning pointing at the env var to set.
    """

    def _sub(match: "re.Match[str]") -> str:
        token = match.group(1)
        env_name = f"{provider_key}_{token}".upper().replace("-", "_")
        from core.infrastructure.secrets import get_secret

        val = (
            get_secret(env_name)
            or get_secret(token)
            or (data.get(token) if isinstance(data.get(token), str) else "")
        )
        if val:
            return str(val)
        import sys

        pm_mod = sys.modules.get("core.provider_manager")
        warned_set = getattr(pm_mod, "_WARNED_BASE_URL_TOKENS", _WARNED_BASE_URL_TOKENS)
        warn_key = (provider_key, token)
        if warn_key not in warned_set:
            warned_set.add(warn_key)
            _WARNED_BASE_URL_TOKENS.add(warn_key)
            logger.warning(
                "Base URL placeholder {%s} for provider '%s' was not resolved. Set %s in environment or secrets.json.",
                token,
                provider_key,
                env_name,
            )
        return match.group(0)

    return _BASE_URL_PLACEHOLDER_RE.sub(_sub, raw)


def _field_float(data: Dict[str, Any], key: str, default: float) -> float:
    """Float config field preserving an explicit 0 (truthiness checks eat it)."""
    raw = data.get(key)
    return default if raw is None else float(raw)


def _field_int(data: Dict[str, Any], key: str, default: int) -> int:
    raw = data.get(key)
    return default if raw is None else int(raw)
