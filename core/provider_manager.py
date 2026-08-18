import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from core.domain.defaults.providers import DEFAULT_JSON_PROVIDERS
from core.infrastructure.adapters.models_source import extract_context_length
from core.infrastructure.platform.paths import CONFIG_DIR, CONFIG_FILE, PROVIDERS_JSON_FILE
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json
from core.infrastructure.runtime.thinking_effort import EFFORT_AUTO, normalize_thinking_effort
from core.models_catalog import cached_json_read, catalog

logger = logging.getLogger(__name__)


# Single source of default values for provider agent tuning knobs. These were
# previously duplicated across create_agent_for_provider and fetch_models fallback.
DEFAULT_CHUNK_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_RETRY_BACKOFF = 2.0
DEFAULT_MAX_RETRY_DELAY = 10.0
DEFAULT_MAX_TOKENS = 8192


@dataclass
class ProviderDef:
    """Structured description of a provider parsed from its JSON definition."""

    key: str
    name: str
    base_url: str = ""
    model: str = ""
    models: List[str] = field(default_factory=list)
    fetch_models: bool = True
    api_type: str = "openai"
    headers: Optional[Dict[str, Any]] = None
    extra_body: Optional[Dict[str, Any]] = None
    reasoning_effort: Optional[str] = None
    chunk_timeout: float = DEFAULT_CHUNK_TIMEOUT
    max_tokens: Optional[int] = None
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY
    retry_backoff: float = DEFAULT_RETRY_BACKOFF
    max_retry_delay: float = DEFAULT_MAX_RETRY_DELAY
    disabled: bool = False
    api_key: str = ""
    requires_key: Optional[bool] = None

    @classmethod
    def from_dict(cls, key: str, data: Dict[str, Any], *, disabled: bool = False) -> "ProviderDef":
        """Build a ProviderDef from a raw provider JSON dict, applying defaults."""
        return cls(
            key=key,
            name=data.get("name") or key,
            base_url=data.get("base_url") or "",
            model=data.get("model") or "",
            models=list(data.get("models") or []),
            fetch_models=bool(data.get("fetch_models", True)),
            api_type=data.get("api_type") or "openai",
            headers=data.get("headers"),
            extra_body=data.get("extra_body"),
            reasoning_effort=data.get("reasoning_effort"),
            chunk_timeout=float(data.get("chunk_timeout") or DEFAULT_CHUNK_TIMEOUT),
            max_tokens=data.get("max_tokens"),
            max_retries=int(data.get("max_retries") or DEFAULT_MAX_RETRIES),
            retry_delay=float(data.get("retry_delay") or DEFAULT_RETRY_DELAY),
            retry_backoff=float(data.get("retry_backoff") or DEFAULT_RETRY_BACKOFF),
            max_retry_delay=float(data.get("max_retry_delay") or DEFAULT_MAX_RETRY_DELAY),
            disabled=disabled,
            api_key=data.get("api_key") or "",
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
            "disabled": self.disabled,
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

    def _save_providers_json(self, data: Dict[str, Any]) -> None:
        atomic_write_json(PROVIDERS_JSON_FILE, data, indent=2)

    def ensure_config_dir(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)

        if not os.path.exists(PROVIDERS_JSON_FILE):
            try:
                self._save_providers_json(DEFAULT_JSON_PROVIDERS)
                self.invalidate_cache()
            except Exception:
                logger.warning("Failed to save default providers JSON", exc_info=True)

    def _load_json_providers(self) -> Dict[str, Dict[str, Any]]:
        providers = dict(DEFAULT_JSON_PROVIDERS)
        data = self._cached_json(PROVIDERS_JSON_FILE, {})
        if isinstance(data, dict):
            try:
                for k, v in data.items():
                    if isinstance(v, dict):
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
            providers[pkey] = ProviderDef.from_dict(pkey, pdata, disabled=pkey in disabled_set).to_dict()
        if len(self._providers_memo) >= 16:
            # FIFO eviction: drop the oldest memo entry. ``dict.popitem`` takes
            # no args (and pops LIFO), so remove the first-inserted key instead.
            self._providers_memo.pop(next(iter(self._providers_memo)))
        self._providers_memo[cache_key] = providers
        return providers

    def load_provider_def(self, provider_key: str) -> Optional[ProviderDef]:
        """Return a structured ProviderDef for a provider (or None if unknown)."""
        providers = self.load_providers(include_disabled=True)
        pdata = providers.get(provider_key)
        if pdata is None:
            return None
        return ProviderDef.from_dict(provider_key, pdata, disabled=pdata.get("disabled", False))

    def get_active_provider_key(self) -> str:
        return self._get_config_data().get("active_provider", "")

    def set_active_provider_key(self, key: str):
        data = self._read_config()
        data["active_provider"] = key
        self._save_config(data)
        self.invalidate_cache()

    def get_api_key(self, key: str) -> str:
        return self._get_config_data().get("api_keys", {}).get(key, "")

    def set_provider_api_key(self, key: str, api_key: str):
        data = self._read_config()
        if "api_keys" not in data:
            data["api_keys"] = {}
        data["api_keys"][key] = api_key
        self._save_config(data)
        self.invalidate_cache()

    def set_provider_model(self, key: str, model_name: str):
        """Saves selected model for provider to config and provider definition"""
        data = self._read_config()
        if "provider_models" not in data:
            data["provider_models"] = {}
        data["provider_models"][key] = model_name
        self._save_config(data)

        # Also update JSON providers file if present
        if os.path.exists(PROVIDERS_JSON_FILE):
            jdata = read_json(PROVIDERS_JSON_FILE, {})
            if isinstance(jdata, dict) and key in jdata:
                try:
                    jdata[key]["model"] = model_name
                    self._save_providers_json(jdata)
                except Exception:
                    logger.exception("Failed to save provider model selection to %s", PROVIDERS_JSON_FILE)
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
        3. First item in provider's 'models' list
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
        return self.create_agent_for_provider(active_key)

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

        # If provider has explicit static models list, return it directly
        if pdef.models:
            return list(pdef.models)

        CACHE_DIR = os.path.join(CONFIG_DIR, "cache")
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(CACHE_DIR, f"models_{provider_key}.json")

        # If no API key set and not local/built-in provider, return configured models list for UI display
        if not api_key and provider_key not in ("ollama",) and not force_refresh:
            if os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                except Exception:
                    pass
            return pdef.models_fallback()

        # 1. Non-blocking fast path when force_refresh is False
        if not force_refresh:
            fallback = pdef.models_fallback()
            cached_models = []
            if os.path.exists(cache_path):
                cdata = read_json(cache_path, {})
                if isinstance(cdata, dict):
                    age = time.time() - cdata.get("updated_at", 0)
                    cached_models = cdata.get("models", [])
                    if age < 86400 and cached_models:
                        return cached_models

            # If no cache and no static fallback list, fetch models directly
            if not cached_models and not fallback and api_key:
                return await self.fetch_models_for_provider(provider_key, force_refresh=True)

            # Trigger background refresh without blocking UI
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self.fetch_models_for_provider(provider_key, force_refresh=True))
            except RuntimeError:
                pass

            return cached_models or fallback

        # 2. Request models via provider HTTP API
        models = []
        model_limits = {}
        should_fetch = pdef.fetch_models
        if base_url and should_fetch:
            models_url = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            timeout_sec = 0.8 if provider_key in ("ollama", "lmstudio") else 3.0
            try:
                async with httpx.AsyncClient() as client:
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

        # Save to cache (including empty/fallback lists with 5-minute TTL)
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
        if not pdata or pdata.get("disabled", False) or provider_key in self.get_disabled_providers():
            return False
        api_type = str(pdata.get("api_type", "openai")).lower()
        if api_type in ("ollama", "lmstudio") or pdata.get("requires_key") is False:
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
            if include_disabled or not p_data.get("disabled", False)
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
