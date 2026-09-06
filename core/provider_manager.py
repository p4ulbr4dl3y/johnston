import logging
import os
import re
from typing import Any, Dict, Optional

from core.domain.defaults.providers import DEFAULT_JSON_PROVIDERS
from core.domain.entities.provider import ProviderDef
from core.domain.policies.provider import split_provider_model
from core.domain.ports.tool_registry import ToolRegistryPort, get_default_tool_registry
from core.infrastructure.adapters.models_source import extract_context_length
from core.infrastructure.config.settings import get_settings
from core.infrastructure.platform.paths import (
    CACHE_DIR,
    CONFIG_DIR,
    CONFIG_FILE,
    PROVIDERS_JSON_FILE,
    provider_models_cache_path,
)
from core.infrastructure.platform.platform_utils import (
    atomic_write_json,
    cached_json_read,
    invalidate_json_read_cache,
    read_json,
    update_json_config,
)
from core.infrastructure.provider_manager import (
    ProviderManagerAgentMixin,
    ProviderManagerConfigMixin,
    ProviderManagerModelsMixin,
)
from core.infrastructure.runtime.thinking_effort import EFFORT_AUTO, normalize_thinking_effort
from core.infrastructure.secrets import (
    get_secret,
    interpolate_secrets,
    interpolate_secrets_in_obj,
    save_secret,
)
from core.models_catalog import catalog

logger = logging.getLogger(__name__)


# Single source of default values for provider agent tuning knobs. These were
# previously duplicated across create_agent_for_provider and fetch_models fallback.
DEFAULT_CHUNK_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_RETRY_BACKOFF = 2.0
DEFAULT_MAX_RETRY_DELAY = 10.0

# Model-list cache lifetimes: a successful fetch lives a full day, an empty
# result only briefly so unreachable providers are retried instead of being
# pinned empty (and instead of refetch-spamming on every UI render).
MODELS_CACHE_TTL = 86400.0
MODELS_CACHE_EMPTY_TTL = 300.0

# Providers whose server runs on localhost and never requires credentials.
LOCAL_PROVIDER_KEYS = ("ollama", "lmstudio", "litellm")

_BASE_URL_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_WARNED_BASE_URL_TOKENS: set = set()


def is_local_provider(
    provider_key: str,
    api_type: str = "",
    base_url: str = "",
    requires_key: Optional[bool] = None,
) -> bool:
    """True for localhost inference servers or providers that never need an API key.

    Single source of truth for local/keyless inference servers across
    fetch_models/is_provider_connected/actions.py.
    """
    if requires_key is False:
        return True
    if (api_type and api_type.lower() in LOCAL_PROVIDER_KEYS) or provider_key.lower() in LOCAL_PROVIDER_KEYS:
        return True
    if base_url:
        low = base_url.lower()
        if (
            "://localhost" in low
            or "://127.0.0.1" in low
            or "://0.0.0.0" in low
            or "://[::1]" in low
        ):
            return True
    return False


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
        val = get_secret(env_name) or get_secret(token) or (data.get(token) if isinstance(data.get(token), str) else "")
        if val:
            return str(val)
        warn_key = (provider_key, token)
        if warn_key not in _WARNED_BASE_URL_TOKENS:
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


def _provider_def_from_dict(
    cls, key: str, data: Dict[str, Any], *, enabled: Optional[bool] = None
) -> ProviderDef:
    """Build a ProviderDef from a raw provider JSON dict, applying defaults and secrets interpolation."""
    raw_key = data.get("api_key") or ""
    resolved_key = interpolate_secrets(raw_key) if raw_key else ""
    raw_base_url = resolve_base_url_placeholders(data.get("base_url") or "", key, data)
    resolved_base_url = interpolate_secrets(raw_base_url)
    headers = interpolate_secrets_in_obj(data.get("headers")) if data.get("headers") else None

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
        chunk_timeout=_field_float(data, "chunk_timeout", get_settings().llm.chunk_timeout),
        max_tokens=data.get("max_tokens"),
        max_retries=_field_int(data, "max_retries", get_settings().llm.max_retries),
        retry_delay=_field_float(data, "retry_delay", get_settings().llm.retry_delay),
        retry_backoff=_field_float(data, "retry_backoff", get_settings().llm.retry_backoff),
        max_retry_delay=_field_float(data, "max_retry_delay", get_settings().llm.max_retry_delay),
        enabled=is_enabled,
        api_key=resolved_key,
        requires_key=data.get("requires_key"),
    )


ProviderDef.from_dict = classmethod(_provider_def_from_dict)


def _file_mtime(path: str) -> float:
    """Best-effort file mtime (0.0 when missing) for cache-signature checks."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


class ProviderManager(ProviderManagerConfigMixin, ProviderManagerModelsMixin, ProviderManagerAgentMixin):
    def __init__(self, tool_registry: Optional[ToolRegistryPort] = None):
        self._tool_registry = tool_registry
        self.invalidate_cache()
        self.ensure_config_dir()

    async def close(self) -> None:
        """Close shared HTTP clients and resources on shutdown."""
        await catalog.close()


__all__ = [
    "CACHE_DIR",
    "CONFIG_DIR",
    "CONFIG_FILE",
    "DEFAULT_CHUNK_TIMEOUT",
    "DEFAULT_JSON_PROVIDERS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MAX_RETRY_DELAY",
    "DEFAULT_RETRY_BACKOFF",
    "DEFAULT_RETRY_DELAY",
    "EFFORT_AUTO",
    "LOCAL_PROVIDER_KEYS",
    "MODELS_CACHE_EMPTY_TTL",
    "MODELS_CACHE_TTL",
    "PROVIDERS_JSON_FILE",
    "ProviderDef",
    "ProviderManager",
    "ProviderManagerAgentMixin",
    "ProviderManagerConfigMixin",
    "ProviderManagerModelsMixin",
    "ToolRegistryPort",
    "atomic_write_json",
    "cached_json_read",
    "catalog",
    "extract_context_length",
    "get_default_tool_registry",
    "get_secret",
    "get_settings",
    "interpolate_secrets",
    "interpolate_secrets_in_obj",
    "invalidate_json_read_cache",
    "is_local_provider",
    "normalize_thinking_effort",
    "provider_models_cache_path",
    "read_json",
    "resolve_base_url_placeholders",
    "save_secret",
    "split_provider_model",
    "update_json_config",
]
