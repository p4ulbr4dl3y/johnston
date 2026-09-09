import logging
import os
from typing import Optional

from johnston.core.application.provider.mixins import (
    ProviderManagerAgentMixin,
    ProviderManagerConfigMixin,
    ProviderManagerModelsMixin,
)
from johnston.core.domain.defaults.providers import DEFAULT_JSON_PROVIDERS
from johnston.core.domain.entities.provider import (
    _WARNED_BASE_URL_TOKENS,
    ProviderDef,
    reset_warned_base_url_tokens,
    resolve_base_url_placeholders,
)
from johnston.core.domain.policies.models_catalog import catalog
from johnston.core.domain.policies.provider import split_provider_model
from johnston.core.domain.ports.tool_registry import ToolRegistryPort, get_default_tool_registry
from johnston.core.infrastructure.config.settings import get_settings
from johnston.core.infrastructure.llm.models.models_source import extract_context_length
from johnston.core.infrastructure.platform.paths import (
    CACHE_DIR,
    CONFIG_DIR,
    CONFIG_FILE,
    PROVIDERS_JSON_FILE,
    provider_models_cache_path,
)
from johnston.core.infrastructure.platform.platform_utils import (
    atomic_write_json,
    cached_json_read,
    invalidate_json_read_cache,
    read_json,
    update_json_config,
)
from johnston.core.infrastructure.runtime.thinking_effort import EFFORT_AUTO, normalize_thinking_effort
from johnston.core.infrastructure.secrets import (
    get_secret,
    interpolate_secrets,
    interpolate_secrets_in_obj,
    save_secret,
)

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


_provider_def_from_dict = ProviderDef.from_dict


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
    "_WARNED_BASE_URL_TOKENS",
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
    "reset_warned_base_url_tokens",
    "resolve_base_url_placeholders",
    "save_secret",
    "split_provider_model",
    "update_json_config",
]
