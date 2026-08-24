import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.domain.defaults.providers import DEFAULT_JSON_PROVIDERS
from core.infrastructure.adapters.models_source import extract_context_length
from core.infrastructure.platform.paths import CACHE_DIR, CONFIG_DIR, CONFIG_FILE, PROVIDERS_JSON_FILE
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json
from core.infrastructure.runtime.background import spawn_background_task
from core.infrastructure.runtime.thinking_effort import EFFORT_AUTO, normalize_thinking_effort
from core.infrastructure.secrets import (
    get_secret,
    interpolate_secrets,
    interpolate_secrets_in_obj,
    save_secret,
)
from core.models_catalog import cached_json_read, catalog, invalidate_json_read_cache

logger = logging.getLogger(__name__)


# Single source of default values for provider agent tuning knobs. These were
# previously duplicated across create_agent_for_provider and fetch_models fallback.
DEFAULT_CHUNK_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_RETRY_BACKOFF = 2.0
DEFAULT_MAX_RETRY_DELAY = 10.0
DEFAULT_MAX_TOKENS = 8192

# Model-list cache lifetimes: a successful fetch lives a full day, an empty
# result only briefly so unreachable providers are retried instead of being
# pinned empty (and instead of refetch-spamming on every UI render).
MODELS_CACHE_TTL = 86400.0
MODELS_CACHE_EMPTY_TTL = 300.0

# Providers whose server runs on localhost and never requires credentials.
LOCAL_PROVIDER_KEYS = ("ollama", "lmstudio", "litellm")

# Conventional env vars that deviate from the <KEY>_API_KEY scheme.
_ENV_KEY_ALIASES = {
    "togetherai": "TOGETHER_API_KEY",
}

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


def env_api_key(provider_key: str) -> str:
    """Resolve API key from environment or centralized ~/.johnston/secrets.json."""
    return get_secret(provider_key)


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


@dataclass
class ProviderDef:
    """Resolved provider definition used across the application."""

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

    @classmethod
    def from_dict(cls, key: str, data: Dict[str, Any], *, enabled: bool = True) -> "ProviderDef":
        """Build a ProviderDef from a raw provider JSON dict, applying defaults and secrets interpolation."""
        raw_key = data.get("api_key") or ""
        resolved_key = interpolate_secrets(raw_key) if raw_key else ""
        raw_base_url = resolve_base_url_placeholders(data.get("base_url") or "", key, data)
        resolved_base_url = interpolate_secrets(raw_base_url)
        headers = interpolate_secrets_in_obj(data.get("headers")) if data.get("headers") else None

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
            chunk_timeout=_field_float(data, "chunk_timeout", DEFAULT_CHUNK_TIMEOUT),
            max_tokens=data.get("max_tokens"),
            max_retries=_field_int(data, "max_retries", DEFAULT_MAX_RETRIES),
            retry_delay=_field_float(data, "retry_delay", DEFAULT_RETRY_DELAY),
            retry_backoff=_field_float(data, "retry_backoff", DEFAULT_RETRY_BACKOFF),
            max_retry_delay=_field_float(data, "max_retry_delay", DEFAULT_MAX_RETRY_DELAY),
            enabled=enabled,
            api_key=resolved_key,
            requires_key=data.get("requires_key"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the dict shape previously returned by load_providers."""
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


def _file_mtime(path: str) -> float:
    """Best-effort file mtime (0.0 when missing) for cache-signature checks."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


class ProviderManager:
    def __init__(self):
        self.invalidate_cache()
        self.ensure_config_dir()

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

    def get_disabled_providers(self) -> List[str]:
        return self._get_config_data().get("disabled_providers", [])

    def set_provider_disabled(self, key: str, disabled: bool):
        data = self._read_config()
        disabled_set = set(data.get("disabled_providers", []))
        if disabled:
            disabled_set.add(key)
        else:
            disabled_set.discard(key)
        data["disabled_providers"] = list(disabled_set)
        self._save_config(data)
        self.invalidate_cache()

    def load_providers(self, include_disabled: bool = True) -> Dict[str, Any]:
        """Loads providers from JSON definitions (memoized until source files change)."""
        disabled_set = set(self.get_disabled_providers())
        # Memo-key: include_disabled + source-file mtimes + disabled set. The
        # result is reused across the many per-turn / footer-render calls and
        # invalidated after any set_* mutation or external config change.
        cfg_mtime = _file_mtime(CONFIG_FILE)
        providers_mtime = _file_mtime(PROVIDERS_JSON_FILE)
        cache_key = (include_disabled, cfg_mtime, providers_mtime, tuple(sorted(disabled_set)))
        cached = self._providers_memo.get(cache_key)
        if cached is not None:
            return cached

        json_providers = self._load_json_providers()
        providers = {}
        for pkey, pdata in json_providers.items():
            if not include_disabled and pkey in disabled_set:
                continue
            # One malformed user entry must never take down provider loading:
            # skip it with a warning (mirrors MCP config validation).
            try:
                providers[pkey] = ProviderDef.from_dict(pkey, pdata, enabled=pkey not in disabled_set).to_dict()
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
        ``enabled`` is derived from the disabled set for both JSON and catalog
        providers. A definition with garbage-typed fields yields None plus a
        warning instead of raising, mirroring ``load_providers`` robustness.
        """
        disabled_set = set(self.get_disabled_providers())
        enabled = provider_key not in disabled_set
        json_providers = self._load_json_providers()
        if provider_key in json_providers:
            try:
                return ProviderDef.from_dict(provider_key, json_providers[provider_key], enabled=enabled)
            except Exception as exc:
                logger.warning("Malformed provider definition %r: %s", provider_key, exc)
                return None
        cat_pdata = catalog.get_catalog_provider(provider_key)
        if cat_pdata is not None:
            try:
                return ProviderDef.from_dict(provider_key, cat_pdata, enabled=enabled)
            except Exception as exc:
                logger.warning("Malformed catalog provider definition %r: %s", provider_key, exc)
                return None
        return None

    def get_catalog_providers(self) -> Dict[str, Dict[str, Any]]:
        """Returns all providers discovered dynamically from models.dev catalog."""
        return catalog.get_discovered_providers()

    def get_active_provider_key(self) -> str:
        return self._get_config_data().get("active_provider", "")

    def set_active_provider_key(self, key: str):
        data = self._read_config()
        data["active_provider"] = key
        self._save_config(data)
        self.invalidate_cache()

    def get_api_key(self, key: str) -> str:
        """Resolve API key for provider *key* from secrets.json, env var, or config."""
        secret = get_secret(key)
        if secret:
            return secret
        stored = self._get_config_data().get("api_keys", {}).get(key, "")
        if stored and str(stored).strip():
            return str(stored)
        return ""

    def set_provider_api_key(self, key: str, api_key: str):
        save_secret(key, api_key)
        self.invalidate_cache()

    def set_provider_model(self, key: str, model_name: str):
        """Saves selected model for provider to config.json.

        Single source of truth: the selection is intentionally NOT mirrored
        into providers.json — the old dual write drifted apart and silently
        skipped catalog-only providers.
        """
        data = self._read_config()
        if "provider_models" not in data:
            data["provider_models"] = {}
        data["provider_models"][key] = model_name
        self._save_config(data)
        self.invalidate_cache()

    def set_provider_thinking_effort(self, provider_key: str, model_name: str, effort: str):
        data = self._read_config()

        efforts = data.setdefault("provider_thinking_efforts", {})
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
        efforts = self._get_config_data().get("provider_thinking_efforts", {})
        provider_efforts = efforts.get(provider_key, {})
        if model_name in provider_efforts:
            norm = normalize_thinking_effort(provider_efforts[model_name])
            if norm:
                return norm

        return EFFORT_AUTO

    def get_provider_model(self, provider_key: str) -> str:
        """Returns active model for specified provider with priority:
        1. Saved user choice in config.json (provider_models)
        2. Explicit 'model' field in provider definition
        3. Empty string when neither is configured — no model is guessed,
           so a misconfigured provider fails loudly instead of silently
           using an arbitrary first entry of its models list.
        """
        providers = self.load_providers()
        if provider_key not in providers:
            return ""

        target_provider = providers[provider_key]

        p_models = self._get_config_data().get("provider_models", {})
        if provider_key in p_models and p_models[provider_key]:
            return p_models[provider_key]

        if target_provider.get("model"):
            return target_provider["model"]

        return ""

    def create_agent_for_provider(self, provider_key: str):
        pdef = self.load_provider_def(provider_key)
        # A disabled provider must never back an agent (enable/disable must be
        # authoritative for actual usage, not just UI filtering). Unknown/None
        # providers keep building a default agent for backward compatibility.
        if pdef is not None and not pdef.enabled:
            logger.warning("Refusing to create agent for disabled provider: %s", provider_key)
            return None
        pkey_str = pdef.key if pdef else (provider_key or "")
        stored_key = self.get_api_key(pkey_str) if pkey_str else ""
        model_val = self.get_provider_model(provider_key) if provider_key else ""
        thinking_effort = self.get_provider_thinking_effort(provider_key, model_val) if provider_key else EFFORT_AUTO

        from core.base_provider import BaseAgent
        from tools.invoke_subagent import InvokeSubagentTool
        from tools.read import process_image_file_sync
        from tools.registry import execute_tool, get_default_tools, normalize_tool_name

        agent = BaseAgent(
            api_key=stored_key or (pdef.api_key if pdef else ""),
            model=model_val,
            base_url=pdef.base_url if pdef else "",
            provider_key=pkey_str,
            api_type=pdef.api_type if pdef else "openai",
            headers=pdef.headers if pdef else None,
            extra_body=pdef.extra_body if pdef else None,
            reasoning_effort=pdef.reasoning_effort if pdef else None,
            thinking_effort=thinking_effort,
            chunk_timeout=pdef.chunk_timeout if pdef else DEFAULT_CHUNK_TIMEOUT,
            max_tokens=(pdef.max_tokens if pdef else None) or DEFAULT_MAX_TOKENS,
            max_retries=pdef.max_retries if pdef else DEFAULT_MAX_RETRIES,
            retry_delay=pdef.retry_delay if pdef else DEFAULT_RETRY_DELAY,
            retry_backoff=pdef.retry_backoff if pdef else DEFAULT_RETRY_BACKOFF,
            max_retry_delay=pdef.max_retry_delay if pdef else DEFAULT_MAX_RETRY_DELAY,
            tool_executor=execute_tool,
            default_tools_provider=get_default_tools,
            image_processor=process_image_file_sync,
            tool_name_normalizer=normalize_tool_name,
        )
        agent.subagent_schema = InvokeSubagentTool.schema
        return agent

    def create_active_agent(self):
        active_key = self.get_active_provider_key()
        agent = self.create_agent_for_provider(active_key)
        if agent is not None:
            return agent
        # Fallback: if the active provider is disabled/unusable, pick the first
        # *connected* (enabled + configured) provider that can build an agent so
        # the app keeps a working agent instead of silently switching to another
        # provider that would fail on the first call for lack of a credential.
        for pkey, pdata in self.load_providers().items():
            if pkey == active_key or not pdata.get("enabled", True):
                continue
            if not self.is_provider_connected(pkey, pdata):
                continue
            agent = self.create_agent_for_provider(pkey)
            if agent is not None:
                self.set_active_provider_key(pkey)
                return agent
        return None

    def recreate_active_agent(self, app: Any, provider_key: Optional[str] = None, history: Optional[List[Any]] = None):
        """Recreates active agent on app preserving history, mode, and UI status."""
        old_history = history if history is not None else list(getattr(getattr(app, "agent", None), "history", []))
        current_role = getattr(app, "role", getattr(getattr(app, "agent", None), "role", "worker"))
        if provider_key:
            self.set_active_provider_key(provider_key)
        agent = self.create_active_agent()
        if agent:
            if old_history:
                agent.history = old_history
            agent.role = current_role
            agent.app = app
        app.agent = agent
        app.role = current_role
        if hasattr(app, "refresh_status_footer"):
            app.refresh_status_footer()
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
                cdata = read_json(cache_path, {})
                if isinstance(cdata, dict):
                    cache_age = time.time() - float(cdata.get("updated_at", 0))
                    cached_models = [m for m in cdata.get("models", []) if isinstance(m, str)]

            if cache_age is not None:
                if cached_models and cache_age < MODELS_CACHE_TTL:
                    return cached_models
                # Recently fetched empty list with nothing better to show:
                # serve it instead of spawning a refetch on every call.
                if not cached_models and not fallback and cache_age < MODELS_CACHE_EMPTY_TTL:
                    return []

            # If no usable cache and no static fallback list, fetch directly
            if not cached_models and not fallback and (api_key or not needs_key):
                return await self.fetch_models_for_provider(provider_key, force_refresh=True)

            # Trigger background refresh without blocking UI.
            spawn_background_task(self.fetch_models_for_provider(provider_key, force_refresh=True))

            return cached_models or fallback

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
                logger.warning("Error fetching models for %s: %s", provider_key, e)

        if models:
            try:
                catalog.save_cache()
            except Exception:
                pass

        # Universal fallback to configured models list or default model
        if not models:
            models = pdef.models_fallback()

        # Save to cache: non-empty lists live MODELS_CACHE_TTL, empty/fallback
        # ones only MODELS_CACHE_EMPTY_TTL (see fast path above).
        try:
            atomic_write_json(
                cache_path, {"updated_at": time.time(), "models": models, "model_limits": model_limits}, indent=2
            )
        except Exception as e:
            logger.warning("Error writing models cache: %s", e)

        return models

    def is_provider_connected(self, provider_key: str, pdata: Optional[Dict[str, Any]] = None) -> bool:
        """Returns True if the provider is connected and not disabled."""
        if pdata is None:
            providers = self.load_providers(include_disabled=True)
            pdata = providers.get(provider_key, {})
        if not pdata or not pdata.get("enabled", True) or provider_key in self.get_disabled_providers():
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
