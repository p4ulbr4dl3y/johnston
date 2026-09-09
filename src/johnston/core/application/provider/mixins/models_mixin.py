import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from johnston.core.infrastructure.adapters.models_source import extract_context_length

logger = logging.getLogger(__name__)


def _pm():
    import johnston.core.application.provider.provider_manager as pm

    return pm


class ProviderManagerModelsMixin:
    async def fetch_models_for_provider(self, provider_key: str, force_refresh: bool = False) -> List[str]:
        """Returns cached list of provider models (TTL = 24h) or performs HTTP request"""
        pdef = self.load_provider_def(provider_key)
        if pdef is None:
            return []

        base_url = pdef.base_url
        api_key = self.get_api_key(provider_key) or pdef.api_key
        needs_key = self.provider_needs_key(provider_key, pdef)

        # If provider has explicit static models list, return it directly
        if pdef.models:
            return list(pdef.models)

        pm = _pm()
        os.makedirs(pm.CACHE_DIR, exist_ok=True)
        cache_path = str(pm.provider_models_cache_path(provider_key))

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
                cdata = await asyncio.to_thread(pm.read_json, cache_path, {})
                if isinstance(cdata, dict):
                    cache_age = time.time() - float(cdata.get("updated_at", 0))
                    cached_models = [m for m in cdata.get("models", []) if isinstance(m, str)]

            if cache_age is not None:
                if cached_models and cache_age < pm.MODELS_CACHE_TTL:
                    return cached_models
                # Recently fetched empty list with nothing better to show:
                # serve it instead of spamming refetches.
                if not cached_models and not fallback and cache_age < pm.MODELS_CACHE_EMPTY_TTL:
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
        fetch_succeeded = False
        if base_url and should_fetch:
            models_url = f"{base_url.rstrip('/')}/models"
            headers = dict(pdef.headers) if pdef.headers else {}
            if api_key and "Authorization" not in headers:
                headers["Authorization"] = f"Bearer {api_key}"
            timeout_sec = (
                1.5
                if pm.is_local_provider(provider_key, pdef.api_type, pdef.base_url, pdef.requires_key)
                else 8.0
            )
            try:
                client = pm.catalog.get_client()
                resp = await client.get(models_url, headers=headers, timeout=timeout_sec)
                if resp.status_code == 200:
                    fetch_succeeded = True
                    data = resp.json()
                    for m in data.get("data", []):
                        if isinstance(m, dict) and "id" in m:
                            m_id = m["id"]
                            models.append(m_id)
                            m_name = m.get("name")
                            if m_name:
                                pm.catalog.update_model_names({m_id: m_name, m_id.split("/")[-1]: m_name})
                            ctx_len = extract_context_length(m)
                            if ctx_len:
                                model_limits[m_id] = ctx_len
            except Exception as e:
                if pm.is_local_provider(provider_key, pdef.api_type, pdef.base_url, pdef.requires_key):
                    logger.debug("Local provider %s not reachable: %s", provider_key, e)
                else:
                    logger.warning("Error fetching models for %s: %s", provider_key, e)

        if fetch_succeeded:
            if models:
                try:
                    await asyncio.to_thread(pm.catalog.save_cache)
                except Exception:
                    pass
            try:
                await asyncio.to_thread(
                    pm.atomic_write_json,
                    cache_path,
                    {"updated_at": time.time(), "models": models, "model_limits": model_limits},
                    indent=2,
                )
            except Exception as e:
                logger.warning("Error writing models cache: %s", e)
            return models

        # If network fetch failed (exception/timeout/non-200), preserve existing cache if present
        if os.path.exists(cache_path):
            cdata = await asyncio.to_thread(pm.read_json, cache_path, {})
            if isinstance(cdata, dict):
                cached_models = [m for m in cdata.get("models", []) if isinstance(m, str)]
                if cached_models:
                    logger.info("Using stale cached models for %s after fetch failure", provider_key)
                    return cached_models

        # Universal fallback to configured models list or default model
        return pdef.models_fallback()

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
        if _pm().is_local_provider(provider_key, api_type, base_url, requires_key):
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
