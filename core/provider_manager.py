import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from core.config import CONFIG_DIR, CONFIG_FILE, PROVIDERS_JSON_FILE
from core.thinking_effort import EFFORT_AUTO, normalize_thinking_effort

DEFAULT_JSON_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "key": "openai",
        "name": "OpenAI",
        "description": "Official OpenAI API provider",
        "base_url": "https://api.openai.com/v1",
        "api_type": "openai",
    },
    "anthropic": {
        "key": "anthropic",
        "name": "Anthropic",
        "description": "Anthropic Claude API provider",
        "base_url": "https://api.anthropic.com/v1",
        "api_type": "anthropic",
    },
    "gemini": {
        "key": "gemini",
        "name": "Gemini",
        "description": "Google Gemini REST API provider",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_type": "gemini",
    },
    "openrouter": {
        "key": "openrouter",
        "name": "OpenRouter",
        "description": "Unified OpenRouter API",
        "base_url": "https://openrouter.ai/api/v1",
        "api_type": "openai",
    },
    "groq": {
        "key": "groq",
        "name": "Groq",
        "description": "Ultra-fast Groq LPU inference",
        "base_url": "https://api.groq.com/openai/v1",
        "api_type": "openai",
    },
    "xai": {
        "key": "xai",
        "name": "xAI",
        "description": "xAI Grok API provider",
        "base_url": "https://api.x.ai/v1",
        "api_type": "openai",
    },
    "mistral": {
        "key": "mistral",
        "name": "Mistral",
        "description": "Mistral AI API provider",
        "base_url": "https://api.mistral.ai/v1",
        "api_type": "openai",
    },
    "togetherai": {
        "key": "togetherai",
        "name": "Together AI",
        "description": "Together AI open-weight model cloud",
        "base_url": "https://api.together.xyz/v1",
        "api_type": "openai",
    },
    "deepinfra": {
        "key": "deepinfra",
        "name": "DeepInfra",
        "description": "High-throughput cost-efficient model server",
        "base_url": "https://api.deepinfra.com/v1/openai",
        "api_type": "openai",
    },
    "fireworks": {
        "key": "fireworks",
        "name": "Fireworks",
        "description": "Fireworks AI fast open-source inference",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "api_type": "openai",
    },
    "cerebras": {
        "key": "cerebras",
        "name": "Cerebras",
        "description": "Cerebras Wafer-Scale Engine high-speed inference",
        "base_url": "https://api.cerebras.ai/v1",
        "api_type": "openai",
    },
    "nvidia": {
        "key": "nvidia",
        "name": "Nvidia",
        "description": "Nvidia NIM multi-model AI agent",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_type": "openai",
    },
    "github-copilot": {
        "key": "github-copilot",
        "name": "GitHub Copilot",
        "description": "GitHub Copilot Chat API endpoint",
        "base_url": "https://api.githubcopilot.com",
        "api_type": "openai",
    },
}


class ProviderManager:
    def __init__(self):
        self.invalidate_cache()
        self.ensure_config_dir()

    def invalidate_cache(self):
        self._config_cache = {}
        self._config_mtime = 0.0
        self._config_file_path = ""
        self._providers_cache = {}
        self._providers_mtime = 0.0
        self._providers_file_path = ""

    def _get_config_data(self) -> dict:
        if not os.path.exists(CONFIG_FILE):
            return {}
        try:
            mtime = os.path.getmtime(CONFIG_FILE)
            if self._config_cache and getattr(self, "_config_file_path", "") == CONFIG_FILE and self._config_mtime == mtime:
                return self._config_cache
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._config_cache = data if isinstance(data, dict) else {}
            self._config_mtime = mtime
            self._config_file_path = CONFIG_FILE
            return self._config_cache
        except Exception:
            return {}

    def _save_config(self, data: Dict[str, Any]) -> None:
        from tools.base import atomic_write_json
        atomic_write_json(CONFIG_FILE, data, indent=2)

    def _save_providers_json(self, data: Dict[str, Any]) -> None:
        from tools.base import atomic_write_json
        atomic_write_json(PROVIDERS_JSON_FILE, data, indent=2)

    def ensure_config_dir(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)

        if not os.path.exists(PROVIDERS_JSON_FILE):
            try:
                self._save_providers_json(DEFAULT_JSON_PROVIDERS)
                self.invalidate_cache()
            except Exception:
                pass

    def _load_json_providers(self) -> Dict[str, Dict[str, Any]]:
        providers = dict(DEFAULT_JSON_PROVIDERS)
        if os.path.exists(PROVIDERS_JSON_FILE):
            try:
                mtime = os.path.getmtime(PROVIDERS_JSON_FILE)
                if self._providers_cache and getattr(self, "_providers_file_path", "") == PROVIDERS_JSON_FILE and self._providers_mtime == mtime:
                    data = self._providers_cache
                else:
                    with open(PROVIDERS_JSON_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._providers_cache = data if isinstance(data, dict) else {}
                    self._providers_mtime = mtime
                    self._providers_file_path = PROVIDERS_JSON_FILE
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, dict):
                            merged = dict(DEFAULT_JSON_PROVIDERS.get(k, {}))
                            merged.update(v)
                            providers[k] = merged
            except Exception:
                pass
        return providers

    def get_disabled_providers(self) -> List[str]:
        return self._get_config_data().get("disabled_providers", [])

    def set_provider_disabled(self, key: str, disabled: bool):
        data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        disabled_set = set(data.get("disabled_providers", []))
        if disabled:
            disabled_set.add(key)
        else:
            disabled_set.discard(key)
        data["disabled_providers"] = list(disabled_set)
        self._save_config(data)
        self.invalidate_cache()

    def load_providers(self, include_disabled: bool = True) -> Dict[str, Any]:
        """Loads providers from JSON definitions"""
        providers = {}
        disabled_set = set(self.get_disabled_providers())

        json_providers = self._load_json_providers()
        for pkey, pdata in json_providers.items():
            if not include_disabled and pkey in disabled_set:
                continue
            providers[pkey] = {
                "key": pkey,
                "name": pdata.get("name", pkey),
                "description": pdata.get("description", ""),
                "base_url": pdata.get("base_url", ""),
                "model": pdata.get("model", ""),
                "models": pdata.get("models", []),
                "fetch_models": pdata.get("fetch_models", True),
                "api_type": pdata.get("api_type", "openai"),
                "headers": pdata.get("headers"),
                "extra_body": pdata.get("extra_body"),
                "reasoning_effort": pdata.get("reasoning_effort"),
                "chunk_timeout": pdata.get("chunk_timeout", 30.0),
                "max_tokens": pdata.get("max_tokens"),
                "max_steps": pdata.get("max_steps"),
                "max_retries": pdata.get("max_retries", 3),
                "retry_delay": pdata.get("retry_delay", 1.0),
                "retry_backoff": pdata.get("retry_backoff", 2.0),
                "max_retry_delay": pdata.get("max_retry_delay", 10.0),
                "disabled": pkey in disabled_set,
                "source": "json",
            }

        return providers

    def get_active_provider_key(self) -> str:
        return self._get_config_data().get("active_provider", "")

    def set_active_provider_key(self, key: str):
        data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["active_provider"] = key
        self._save_config(data)
        self.invalidate_cache()

    def get_api_key(self, key: str) -> str:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    api_keys = data.get("api_keys", {})
                    if key in api_keys and api_keys[key]:
                        return api_keys[key]
            except Exception:
                pass
        return os.getenv(f"{key.upper()}_API_KEY", "")

    def set_provider_api_key(self, key: str, api_key: str):
        data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        if "api_keys" not in data:
            data["api_keys"] = {}
        data["api_keys"][key] = api_key
        self._save_config(data)
        self.invalidate_cache()

    def set_provider_model(self, key: str, model_name: str):
        """Saves selected model for provider to config and provider definition"""
        data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        if "provider_models" not in data:
            data["provider_models"] = {}
        data["provider_models"][key] = model_name
        self._save_config(data)

        # Also update JSON providers file if present
        if os.path.exists(PROVIDERS_JSON_FILE):
            try:
                with open(PROVIDERS_JSON_FILE, "r", encoding="utf-8") as f:
                    jdata = json.load(f)
                if key in jdata:
                    jdata[key]["model"] = model_name
                    self._save_providers_json(jdata)
            except Exception:
                pass
        self.invalidate_cache()

    def set_provider_thinking_effort(self, provider_key: str, model_name: str, effort: str):
        data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

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
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                efforts = data.get("provider_thinking_efforts", {})
                provider_efforts = efforts.get(provider_key, {})
                if model_name and model_name in provider_efforts:
                    norm = normalize_thinking_effort(provider_efforts[model_name])
                    if norm:
                        return norm
            except Exception:
                pass

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

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    p_models = cdata.get("provider_models", {})
                    if provider_key in p_models and p_models[provider_key]:
                        return p_models[provider_key]
            except Exception:
                pass

        if target_provider.get("model"):
            return target_provider["model"]

        return ""

    def create_agent_for_provider(self, provider_key: str):
        providers = self.load_providers()
        target_provider = providers.get(provider_key, {})
        pkey_str = target_provider.get("key", provider_key)
        stored_key = self.get_api_key(pkey_str) if pkey_str else ""
        model_val = self.get_provider_model(provider_key) if provider_key else ""
        thinking_effort = self.get_provider_thinking_effort(provider_key, model_val) if provider_key else EFFORT_AUTO

        from core.base_provider import BaseAgent

        return BaseAgent(
            api_key=stored_key or target_provider.get("api_key", ""),
            model=model_val,
            base_url=target_provider.get("base_url", ""),
            provider_key=pkey_str,
            api_type=target_provider.get("api_type", "openai"),
            headers=target_provider.get("headers"),
            extra_body=target_provider.get("extra_body"),
            reasoning_effort=target_provider.get("reasoning_effort"),
            thinking_effort=thinking_effort,
            chunk_timeout=target_provider.get("chunk_timeout", 30.0),
            max_tokens=target_provider.get("max_tokens") or 8192,
            max_steps=target_provider.get("max_steps") or 50,
            max_retries=target_provider.get("max_retries", 3),
            retry_delay=target_provider.get("retry_delay", 1.0),
            retry_backoff=target_provider.get("retry_backoff", 2.0),
            max_retry_delay=target_provider.get("max_retry_delay", 10.0),
        )

    def create_active_agent(self):
        active_key = self.get_active_provider_key()
        return self.create_agent_for_provider(active_key)

    async def fetch_models_for_provider(self, provider_key: str, force_refresh: bool = False) -> List[str]:
        """Returns cached list of provider models (TTL = 24h) or performs HTTP request"""
        providers = self.load_providers()
        if provider_key not in providers:
            return []

        pdata = providers[provider_key]
        base_url = pdata.get("base_url")
        api_key = self.get_api_key(provider_key) or pdata.get("api_key")

        # If provider has explicit static models list, return it directly
        if pdata.get("models"):
            return list(pdata["models"])

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
            return pdata.get("models") or ([pdata["model"]] if pdata.get("model") else [])

        # 1. Non-blocking fast path when force_refresh is False
        if not force_refresh:
            fallback = pdata.get("models") or ([pdata["model"]] if pdata.get("model") else [])
            cached_models = []
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        cdata = json.load(f)
                        age = time.time() - cdata.get("updated_at", 0)
                        cached_models = cdata.get("models", [])
                        if age < 86400 and cached_models:
                            return cached_models
                except Exception:
                    pass

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
        should_fetch = pdata.get("fetch_models", True)
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
                                ctx_len = (
                                    m.get("context_length")
                                    or (m.get("top_provider", {}) or {}).get("context_length")
                                    or m.get("context_window")
                                    or m.get("max_context_length")
                                )
                                if ctx_len and isinstance(ctx_len, (int, float)):
                                    model_limits[m_id] = int(ctx_len)
            except Exception as e:
                print(f"Error fetching models for {provider_key}: {e}")

        # Universal fallback to configured models list or default model
        if not models:
            models = pdata.get("models") or ([pdata["model"]] if pdata.get("model") else [])

        # Save to cache (including empty/fallback lists with 5-minute TTL)
        try:
            from tools.base import atomic_write_json
            atomic_write_json(
                cache_path,
                {"updated_at": time.time(), "models": models, "model_limits": model_limits},
                indent=2
            )
        except Exception as e:
            print(f"Error writing models cache: {e}")

        return models

    def is_provider_connected(self, provider_key: str, pdata: Optional[Dict[str, Any]] = None) -> bool:
        """Returns True if the provider is connected (has API key configured or is local like Ollama/LM Studio)."""
        if pdata is None:
            providers = self.load_providers()
            pdata = providers.get(provider_key, {})
        if not pdata:
            return False
        api_type = str(pdata.get("api_type", "openai")).lower()
        if api_type in ("ollama", "lmstudio") or pdata.get("requires_key") is False:
            return True
        key_val = self.get_api_key(provider_key) or pdata.get("api_key", "")
        return bool(key_val and str(key_val).strip())

    async def fetch_models_grouped(self, force_refresh: bool = False, connected_only: bool = True, include_disabled: bool = False) -> Dict[str, Dict[str, Any]]:
        """Returns model dictionaries grouped by provider (only connected/configured providers by default)"""
        providers = self.load_providers(include_disabled=include_disabled)
        active_providers = [
            (p_key, p_data) for p_key, p_data in providers.items()
            if include_disabled or not p_data.get("disabled", False)
        ]
        if connected_only:
            connected = [
                (p_key, p_data) for p_key, p_data in active_providers
                if self.is_provider_connected(p_key, p_data)
            ]
            if connected:
                active_providers = connected
            else:
                return {}

        results = await asyncio.gather(*[
            self.fetch_models_for_provider(p_key, force_refresh=force_refresh)
            for p_key, _ in active_providers
        ], return_exceptions=True)

        grouped = {}
        for (p_key, p_data), res in zip(active_providers, results):
            if isinstance(res, list) and res:
                grouped[p_key] = {
                    "name": p_data["name"],
                    "models": res
                }
        return grouped
