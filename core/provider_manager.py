import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from core.domain.defaults.providers import DEFAULT_JSON_PROVIDERS
from core.domain.entities.provider import ProviderDef
from core.domain.ports.tool_registry import ToolRegistryPort, get_default_tool_registry
from core.infrastructure.adapters.models_source import extract_context_length
from core.infrastructure.config.settings import get_settings
from core.infrastructure.platform.paths import CACHE_DIR, CONFIG_DIR, CONFIG_FILE, PROVIDERS_JSON_FILE
from core.infrastructure.platform.platform_utils import (
    atomic_write_json,
    cached_json_read,
    invalidate_json_read_cache,
    read_json,
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


class ProviderManager:
    def __init__(self, tool_registry: Optional[ToolRegistryPort] = None):
        self._tool_registry = tool_registry
        self.invalidate_cache()
        self.ensure_config_dir()

    def set_tool_registry(self, registry: Optional[ToolRegistryPort]) -> None:
        self._tool_registry = registry

    def invalidate_cache(self):
        self._providers_memo = {}
        invalidate_json_read_cache(CONFIG_FILE)
        invalidate_json_read_cache(PROVIDERS_JSON_FILE)

    async def close(self) -> None:
        """Close shared HTTP clients and resources on shutdown."""
        await catalog.close()

    def _cached_json(self, path: str, default: Any) -> Any:
        """Reads a JSON file, returning a cached value when the file is unchanged (by mtime).

        Delegates to the shared path+mtime JSON cache in models_catalog so the
        duplicate caching logic is not maintained in two places.
        """
        data = cached_json_read(path, default)
        return data if isinstance(data, dict) else {}

    def _get_config_data(self) -> dict:
        return self._cached_json(CONFIG_FILE, {})

    def _read_config(self) -> dict:
        """Reads CONFIG_FILE, falling back to {} on missing/corrupt file."""
        data = read_json(CONFIG_FILE, {})
        return data if isinstance(data, dict) else {}

    def _save_config(self, data: Dict[str, Any]) -> None:
        atomic_write_json(CONFIG_FILE, data, indent=2)
        invalidate_json_read_cache(CONFIG_FILE)

    def _save_providers_json(self, data: Dict[str, Any]) -> None:
        atomic_write_json(PROVIDERS_JSON_FILE, data, indent=2)
        invalidate_json_read_cache(PROVIDERS_JSON_FILE)

    def ensure_config_dir(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)

        if not os.path.exists(PROVIDERS_JSON_FILE):
            try:
                self._save_providers_json(DEFAULT_JSON_PROVIDERS)
                self.invalidate_cache()
            except Exception:
                logger.warning("Failed to save default providers JSON", exc_info=True)

    def _load_json_providers(self) -> Dict[str, Dict[str, Any]]:
        """Merge user providers.json over built-in defaults.

        User entries are merged field-wise over the matching default (if any);
        custom keys are added as-is; ``"<key>": null`` removes a built-in
        default entirely so users can prune the built-in list permanently.
        """
        providers = dict(DEFAULT_JSON_PROVIDERS)
        data = self._cached_json(PROVIDERS_JSON_FILE, {})
        if isinstance(data, dict):
            try:
                deleted = {k for k, v in data.items() if v is None}
                for k in deleted:
                    providers.pop(k, None)
                for k, v in data.items():
                    if k in deleted or not isinstance(v, dict):
                        continue
                    merged = dict(DEFAULT_JSON_PROVIDERS.get(k, {}))
                    merged.update(v)
                    providers[k] = merged
            except Exception:
                logger.warning("Failed to merge JSON providers", exc_info=True)
        return providers

    def _read_providers_json(self) -> dict:
        """Reads PROVIDERS_JSON_FILE directly, falling back to {} on missing/corrupt file."""
        data = read_json(PROVIDERS_JSON_FILE, {})
        return data if isinstance(data, dict) else {}

    def get_disabled_providers(self) -> List[str]:
        json_providers = self._load_json_providers()
        return [k for k, v in json_providers.items() if not v.get("enabled", True)]

    def set_provider_disabled(self, key: str, disabled: bool):
        data = self._read_providers_json()
        prov_data = data.get(key)
        if not isinstance(prov_data, dict):
            prov_data = {}
        prov_data["enabled"] = not disabled
        data[key] = prov_data
        self._save_providers_json(data)
        self.invalidate_cache()

    def load_providers(self, include_disabled: bool = True) -> Dict[str, Any]:
        """Loads providers from JSON definitions (memoized until source files change)."""
        providers_mtime = _file_mtime(PROVIDERS_JSON_FILE)
        cache_key = (include_disabled, providers_mtime)
        cached = self._providers_memo.get(cache_key)
        if cached is not None:
            return cached

        json_providers = self._load_json_providers()
        providers = {}
        for pkey, pdata in json_providers.items():
            is_enabled = bool(pdata.get("enabled", True))
            if not include_disabled and not is_enabled:
                continue
            # One malformed user entry must never take down provider loading:
            # skip it with a warning (mirrors MCP config validation).
            try:
                providers[pkey] = ProviderDef.from_dict(pkey, pdata, enabled=is_enabled).to_dict()
            except Exception as exc:
                logger.warning("Skipping malformed provider definition %r: %s", pkey, exc)
        if len(self._providers_memo) >= 16:
            # FIFO eviction: drop the oldest memo entry. ``dict.popitem`` takes
            # no args (and pops LIFO), so remove the first-inserted key instead.
            self._providers_memo.pop(next(iter(self._providers_memo)))
        self._providers_memo[cache_key] = providers
        return providers

    def load_provider_def(self, provider_key: str) -> Optional[ProviderDef]:
        """Return a structured ProviderDef for a provider (or None if unknown/malformed).

        Reads the raw JSON definition directly (not the ``load_providers``
        ``to_dict`` shape) so provider fields that ``to_dict`` intentionally
        drops (``requires_key``, ``api_key``, ``fetch_models``, ...) are kept.
        A definition with garbage-typed fields yields None plus a warning
        instead of raising, mirroring ``load_providers`` robustness.
        """
        json_providers = self._load_json_providers()
        if provider_key in json_providers:
            try:
                return ProviderDef.from_dict(provider_key, json_providers[provider_key])
            except Exception as exc:
                logger.warning("Malformed provider definition %r: %s", provider_key, exc)
                return None
        cat_pdata = catalog.get_catalog_provider(provider_key)
        if cat_pdata is not None:
            try:
                return ProviderDef.from_dict(provider_key, cat_pdata, enabled=True)
            except Exception as exc:
                logger.warning("Malformed catalog provider definition %r: %s", provider_key, exc)
                return None
        return None

    def get_catalog_providers(self) -> Dict[str, Dict[str, Any]]:
        """Returns all providers discovered dynamically from models.dev catalog."""
        return catalog.get_discovered_providers()

    def get_active_provider_key(self) -> str:
        """Active provider derived solely from ``model``.

        ``model`` is the single source of truth and always encodes the provider
        either as ``provider/model`` or as a bare ``provider`` key.  The provider
        is extracted directly; the legacy ``active_provider`` field is never read
        or written.
        """
        cfg_model = self._get_config_data().get("model", "")
        if isinstance(cfg_model, str) and cfg_model.strip():
            raw = cfg_model.strip()
            if "/" in raw:
                return raw.split("/", 1)[0].strip().lower()
            return raw.strip().lower()
        return ""

    def set_active_provider_key(self, key: str):
        data = self._read_config()
        if key is None:
            data.pop("model", None)
        else:
            cur_model = self.get_provider_model(key)
            if cur_model:
                data["model"] = f"{key}/{cur_model}"
            else:
                data["model"] = key
        self._save_config(data)
        self.invalidate_cache()

    def get_api_key(self, key: str) -> str:
        """Resolve API key for provider *key* from secrets.json or env var."""
        return get_secret(key)

    def set_provider_api_key(self, key: str, api_key: str):
        save_secret(key, api_key)
        self.invalidate_cache()

    def set_provider_model(self, key: str, model_name: str):
        """Saves selected model to config.json as ``model: key/model_name``."""
        data = self._read_config()
        data["model"] = f"{key}/{model_name}" if model_name else key
        self._save_config(data)
        self.invalidate_cache()

    def set_provider_thinking_effort(self, provider_key: str, model_name: str, effort: str):
        data = self._read_config()
        llm_sec = data.setdefault("llm", {})
        if not isinstance(llm_sec, dict):
            llm_sec = {}
            data["llm"] = llm_sec
        efforts = llm_sec.setdefault("thinking_efforts", {})
        if not isinstance(efforts, dict):
            efforts = {}
            llm_sec["thinking_efforts"] = efforts

        provider_efforts = efforts.setdefault(provider_key, {})
        normalized = normalize_thinking_effort(effort)
        if normalized:
            provider_efforts[model_name] = normalized
        else:
            provider_efforts.pop(model_name, None)
            if not provider_efforts:
                efforts.pop(provider_key, None)

        self._save_config(data)
        self.invalidate_cache()

    def get_provider_thinking_effort(self, provider_key: str, model_name: str = "") -> str:
        cfg = self._get_config_data()
        llm_sec = cfg.get("llm", {})
        efforts = llm_sec.get("thinking_efforts", {}) if isinstance(llm_sec, dict) else {}
        provider_efforts = efforts.get(provider_key, {}) if isinstance(efforts, dict) else {}
        if model_name in provider_efforts:
            norm = normalize_thinking_effort(provider_efforts[model_name])
            if norm:
                return norm

        return EFFORT_AUTO

    def get_provider_model(self, provider_key: str) -> str:
        """Returns active model for specified provider with priority:
        1. Saved user choice in config.json (model: provider/model)
        2. Explicit 'model' field in the provider definition (used when the config
           model is the bare provider key, i.e. no specific model selected yet)
        3. Empty string when neither is configured.
        """
        providers = self.load_providers()
        target_provider = providers.get(provider_key)
        p_def = self.load_provider_def(provider_key) if target_provider is None else None

        if target_provider is None and p_def is None:
            return ""

        default_model = target_provider.get("model") if target_provider else (p_def.model if p_def else "")

        cfg_model = self._get_config_data().get("model", "")
        if isinstance(cfg_model, str) and cfg_model.strip():
            raw = cfg_model.strip()
            if "/" in raw:
                p_key, m_name = raw.split("/", 1)
                if p_key.strip().lower() == provider_key.strip().lower():
                    return m_name.strip()
            elif raw.strip().lower() == provider_key.strip().lower():
                # ``model`` is the bare provider key: fall back to its default model.
                if default_model:
                    return default_model
                return ""

        if default_model:
            return default_model

        return ""

    def create_agent_for_provider(
        self, provider_key: str, tool_registry: Optional[ToolRegistryPort] = None
    ):
        pdef = self.load_provider_def(provider_key)
        if pdef is None:
            return None
        if not pdef.enabled:
            logger.warning("Refusing to create agent for disabled provider: %s", provider_key)
            return None
        pkey_str = pdef.key
        stored_key = self.get_api_key(pkey_str)
        model_val = self.get_provider_model(provider_key)
        thinking_effort = self.get_provider_thinking_effort(provider_key, model_val)

        from core.base_provider import BaseAgent
        from core.infrastructure.runtime.tool_name import normalize_tool_name

        reg = tool_registry or self._tool_registry or get_default_tool_registry()
        tool_executor = reg.execute_tool if reg is not None else None
        default_tools_provider = reg.get_default_tools if reg is not None else None
        image_processor = reg.process_image_file if reg is not None else None
        subagent_schema = reg.get_subagent_schema() if reg is not None else None

        agent = BaseAgent(
            api_key=stored_key or pdef.api_key,
            model=model_val,
            base_url=pdef.base_url,
            provider_key=pkey_str,
            api_type=pdef.api_type,
            headers=pdef.headers,
            extra_body=pdef.extra_body,
            reasoning_effort=pdef.reasoning_effort,
            thinking_effort=thinking_effort,
            chunk_timeout=pdef.chunk_timeout,
            max_tokens=pdef.max_tokens or get_settings().llm.default_max_tokens,
            max_retries=pdef.max_retries,
            retry_delay=pdef.retry_delay,
            retry_backoff=pdef.retry_backoff,
            max_retry_delay=pdef.max_retry_delay,
            tool_executor=tool_executor,
            default_tools_provider=default_tools_provider,
            image_processor=image_processor,
            tool_name_normalizer=normalize_tool_name,
        )
        if subagent_schema is not None:
            agent.subagent_schema = subagent_schema
        return agent

    def create_active_agent(self):
        active_key = self.get_active_provider_key()
        if not active_key:
            return None
        return self.create_agent_for_provider(active_key)

    def recreate_active_agent(
        self,
        provider_key: Optional[str] = None,
        history: Optional[List[Any]] = None,
        role: Optional[str] = None,
    ) -> Any:
        """Recreates active agent preserving history and role."""
        if provider_key:
            self.set_active_provider_key(provider_key)
        agent = self.create_active_agent()
        if agent is not None:
            if history is not None:
                agent.history = list(history)
            if role is not None:
                agent.role = role
        return agent

    async def fetch_models_for_provider(self, provider_key: str, force_refresh: bool = False) -> List[str]:
        """Returns cached list of provider models (TTL = 24h) or performs HTTP request"""
        pdef = self.load_provider_def(provider_key)
        if pdef is None:
            return []

        base_url = pdef.base_url
        api_key = self.get_api_key(provider_key) or pdef.api_key
        needs_key = pdef.requires_key is not False and not is_local_provider(
            provider_key, pdef.api_type, pdef.base_url, pdef.requires_key
        )

        # If provider has explicit static models list, return it directly
        if pdef.models:
            return list(pdef.models)

        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(CACHE_DIR, f"models_{provider_key}.json")

        # If no API key set and not local/built-in provider, return configured models list for UI display
        if needs_key and not api_key and not force_refresh:
            if os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                except Exception:
                    pass
            return pdef.models_fallback()

        # 1. Non-blocking fast path when force_refresh is False
        if not force_refresh:
            fallback = pdef.models_fallback()
            cached_models: List[str] = []
            cache_age: Optional[float] = None
            if os.path.exists(cache_path):
                cdata = await asyncio.to_thread(read_json, cache_path, {})
                if isinstance(cdata, dict):
                    cache_age = time.time() - float(cdata.get("updated_at", 0))
                    cached_models = [m for m in cdata.get("models", []) if isinstance(m, str)]

            if cache_age is not None:
                if cached_models and cache_age < MODELS_CACHE_TTL:
                    return cached_models
                # Recently fetched empty list with nothing better to show:
                # serve it instead of spamming refetches.
                if not cached_models and not fallback and cache_age < MODELS_CACHE_EMPTY_TTL:
                    return []

            if cached_models:
                return cached_models
            if fallback:
                return fallback
            return []

        # 2. Request models via provider HTTP API
        models = []
        model_limits = {}
        should_fetch = pdef.fetch_models
        if base_url and should_fetch:
            models_url = f"{base_url.rstrip('/')}/models"
            headers = dict(pdef.headers) if pdef.headers else {}
            if api_key and "Authorization" not in headers:
                headers["Authorization"] = f"Bearer {api_key}"
            timeout_sec = (
                0.8
                if is_local_provider(provider_key, pdef.api_type, pdef.base_url, pdef.requires_key)
                else 3.0
            )
            try:
                client = catalog.get_client()
                resp = await client.get(models_url, headers=headers, timeout=timeout_sec)
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", []):
                        if isinstance(m, dict) and "id" in m:
                            m_id = m["id"]
                            models.append(m_id)
                            m_name = m.get("name")
                            if m_name:
                                catalog.update_model_names({m_id: m_name, m_id.split("/")[-1]: m_name})
                            ctx_len = extract_context_length(m)
                            if ctx_len:
                                model_limits[m_id] = ctx_len
            except Exception as e:
                if is_local_provider(provider_key, pdef.api_type, pdef.base_url, pdef.requires_key):
                    logger.debug("Local provider %s not reachable: %s", provider_key, e)
                else:
                    logger.warning("Error fetching models for %s: %s", provider_key, e)

        if models:
            try:
                await asyncio.to_thread(catalog.save_cache)
            except Exception:
                pass

        # Universal fallback to configured models list or default model
        if not models:
            models = pdef.models_fallback()

        # Save to cache: non-empty lists live MODELS_CACHE_TTL, empty/fallback
        # ones only MODELS_CACHE_EMPTY_TTL (see fast path above).
        try:
            await asyncio.to_thread(
                atomic_write_json,
                cache_path,
                {"updated_at": time.time(), "models": models, "model_limits": model_limits},
                indent=2,
            )
        except Exception as e:
            logger.warning("Error writing models cache: %s", e)

        return models

    def is_provider_connected(self, provider_key: str, pdata: Optional[Dict[str, Any]] = None) -> bool:
        """Returns True if the provider is connected and not disabled."""
        if pdata is None:
            providers = self.load_providers(include_disabled=True)
            pdata = providers.get(provider_key, {})
        if not pdata or not pdata.get("enabled", True):
            return False
        api_type = str(pdata.get("api_type", "openai")).lower()
        base_url = str(pdata.get("base_url", ""))
        requires_key = pdata.get("requires_key")
        if is_local_provider(provider_key, api_type, base_url, requires_key):
            return True
        key_val = self.get_api_key(provider_key) or pdata.get("api_key", "")
        return bool(key_val and str(key_val).strip())

    async def fetch_models_grouped(
        self, force_refresh: bool = False, connected_only: bool = True, include_disabled: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        """Returns model dictionaries grouped by provider (only connected/configured providers by default)"""
        providers = self.load_providers(include_disabled=include_disabled)
        active_providers = [
            (p_key, p_data)
            for p_key, p_data in providers.items()
            if include_disabled or p_data.get("enabled", True)
        ]
        if connected_only:
            connected = [
                (p_key, p_data) for p_key, p_data in active_providers if self.is_provider_connected(p_key, p_data)
            ]
            if connected:
                active_providers = connected
            else:
                return {}

        results = await asyncio.gather(
            *[self.fetch_models_for_provider(p_key, force_refresh=force_refresh) for p_key, _ in active_providers],
            return_exceptions=True,
        )

        grouped = {}
        for (p_key, p_data), res in zip(active_providers, results):
            if isinstance(res, list) and res:
                grouped[p_key] = {"name": p_data["name"], "models": res}
        return grouped
