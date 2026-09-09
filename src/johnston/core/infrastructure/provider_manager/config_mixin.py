import logging
import os
from typing import Any, Dict, List, Optional

from johnston.core.domain.entities.provider import ProviderDef
from johnston.core.domain.policies.provider import split_provider_model
from johnston.core.infrastructure.runtime.thinking_effort import EFFORT_AUTO, normalize_thinking_effort
from johnston.core.infrastructure.secrets import get_secret, save_secret

logger = logging.getLogger(__name__)


def _pm():
    import johnston.core.application.provider.provider_manager as pm

    return pm


class ProviderManagerConfigMixin:
    _providers_memo: Dict[Any, Any]

    def invalidate_cache(self):
        self._providers_memo = {}
        pm = _pm()
        pm.invalidate_json_read_cache(pm.CONFIG_FILE)
        pm.invalidate_json_read_cache(pm.PROVIDERS_JSON_FILE)

    def _cached_json(self, path: str, default: Any) -> Any:
        """Reads a JSON file, returning a cached value when the file is unchanged (by mtime).

        Delegates to the shared path+mtime JSON cache in models_catalog so the
        duplicate caching logic is not maintained in two places.
        """
        data = _pm().cached_json_read(path, default)
        return data if isinstance(data, dict) else {}

    def _get_config_data(self) -> dict:
        return self._cached_json(_pm().CONFIG_FILE, {})

    def _read_config(self) -> dict:
        """Reads CONFIG_FILE, falling back to {} on missing/corrupt file."""
        data = _pm().read_json(_pm().CONFIG_FILE, {})
        return data if isinstance(data, dict) else {}

    def _save_config(self, data: Dict[str, Any]) -> None:
        _pm().update_json_config(_pm().CONFIG_FILE, lambda cfg: (cfg.clear(), cfg.update(data)), indent=2)

    def _save_providers_json(self, data: Dict[str, Any]) -> None:
        _pm().update_json_config(_pm().PROVIDERS_JSON_FILE, lambda cfg: (cfg.clear(), cfg.update(data)), indent=2)

    def ensure_config_dir(self):
        pm = _pm()
        os.makedirs(pm.CONFIG_DIR, exist_ok=True)

        if not os.path.exists(pm.PROVIDERS_JSON_FILE):
            try:
                self._save_providers_json({})
                self.invalidate_cache()
            except Exception:
                logger.warning("Failed to initialize providers JSON", exc_info=True)

    def _load_json_providers(self) -> Dict[str, Dict[str, Any]]:
        """Merge user providers.json over built-in defaults.

        User entries are merged field-wise over the matching default (if any);
        custom keys are added as-is; ``"<key>": null`` removes a built-in
        default entirely so users can prune the built-in list permanently.
        """
        pm = _pm()
        providers = dict(pm.DEFAULT_JSON_PROVIDERS)
        data = self._cached_json(pm.PROVIDERS_JSON_FILE, {})
        if isinstance(data, dict):
            try:
                deleted = {k for k, v in data.items() if v is None}
                for k in deleted:
                    providers.pop(k, None)
                for k, v in data.items():
                    if k in deleted or not isinstance(v, dict):
                        continue
                    merged = dict(pm.DEFAULT_JSON_PROVIDERS.get(k, {}))
                    merged.update(v)
                    providers[k] = merged
            except Exception:
                logger.warning("Failed to merge JSON providers", exc_info=True)
        return providers

    def _read_providers_json(self) -> dict:
        """Reads PROVIDERS_JSON_FILE directly, falling back to {} on missing/corrupt file."""
        data = _pm().read_json(_pm().PROVIDERS_JSON_FILE, {})
        return data if isinstance(data, dict) else {}

    def get_disabled_providers(self) -> List[str]:
        json_providers = self._load_json_providers()
        return [k for k, v in json_providers.items() if not v.get("enabled", True)]

    def set_provider_disabled(self, key: str, disabled: bool) -> bool:
        if key not in self.load_providers(include_disabled=True):
            return False
        pm = _pm()

        def _mutate(cfg: Dict[str, Any]) -> None:
            prov_data = cfg.get(key)
            if not isinstance(prov_data, dict):
                prov_data = {}
            if disabled:
                prov_data["enabled"] = False
                cfg[key] = prov_data
            else:
                prov_data.pop("enabled", None)
                if not prov_data and key in pm.DEFAULT_JSON_PROVIDERS:
                    cfg.pop(key, None)
                else:
                    prov_data["enabled"] = True
                    cfg[key] = prov_data

        pm.update_json_config(pm.PROVIDERS_JSON_FILE, _mutate, indent=2)
        self.invalidate_cache()
        return True

    def add_provider(
        self,
        name: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        pm = _pm()

        def _mutate(cfg: Dict[str, Any]) -> None:
            prov_data = cfg.get(name)
            if not isinstance(prov_data, dict):
                prov_data = {}
            prov_data["key"] = name
            prov_data["name"] = prov_data.get("name", name)
            prov_data["model"] = model
            models = prov_data.get("models")
            if not isinstance(models, list):
                prov_data["models"] = [model]
            elif model not in models:
                models.append(model)
            if base_url:
                prov_data["base_url"] = base_url
            prov_data.update(kwargs)
            cfg[name] = prov_data

        pm.update_json_config(pm.PROVIDERS_JSON_FILE, _mutate, indent=2)
        if api_key:
            self.set_provider_api_key(name, api_key)
        self.invalidate_cache()

    def remove_provider(self, key: str) -> bool:
        pm = _pm()
        existed = key in self.load_providers(include_disabled=True)

        def _mutate(cfg: Dict[str, Any]) -> None:
            nonlocal existed
            if key in cfg:
                existed = True
            if key in pm.DEFAULT_JSON_PROVIDERS:
                cfg[key] = None
            else:
                cfg.pop(key, None)

        pm.update_json_config(pm.PROVIDERS_JSON_FILE, _mutate, indent=2)
        self.invalidate_cache()
        return existed

    def load_providers(self, include_disabled: bool = True) -> Dict[str, Any]:
        """Loads providers from JSON definitions (memoized until source files change)."""
        pm = _pm()
        providers_mtime = pm._file_mtime(pm.PROVIDERS_JSON_FILE)
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
        pm = _pm()
        json_providers = self._load_json_providers()
        if provider_key in json_providers:
            try:
                return ProviderDef.from_dict(provider_key, json_providers[provider_key])
            except Exception as exc:
                logger.warning("Malformed provider definition %r: %s", provider_key, exc)
                return None
        cat_pdata = pm.catalog.get_catalog_provider(provider_key)
        if cat_pdata is not None:
            try:
                return ProviderDef.from_dict(provider_key, cat_pdata, enabled=True)
            except Exception as exc:
                logger.warning("Malformed catalog provider definition %r: %s", provider_key, exc)
                return None
        return None

    def provider_needs_key(self, provider_key: str, pdef: ProviderDef) -> bool:
        """True when the provider requires an API key (not local/keyless)."""
        pm = _pm()
        return pdef.requires_key is not False and not pm.is_local_provider(
            provider_key, pdef.api_type, pdef.base_url, pdef.requires_key
        )

    def get_catalog_providers(self) -> Dict[str, Dict[str, Any]]:
        """Returns all providers discovered dynamically from models.dev catalog."""
        return _pm().catalog.get_discovered_providers()

    def get_active_provider_key(self) -> str:
        """Active provider derived solely from ``model``.

        ``model`` is the single source of truth and always encodes the provider
        either as ``provider/model`` or as a bare ``provider`` key.  The provider
        is extracted directly; the legacy ``active_provider`` field is never read
        or written.
        """
        cfg_model = self._get_config_data().get("model", "")
        provider, _ = split_provider_model(cfg_model)
        return provider or ""

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
        p_key, m_name = split_provider_model(cfg_model)
        if p_key == provider_key.strip().lower():
            if m_name is not None:
                return m_name
            # ``model`` is the bare provider key: fall back to its default model.
            if default_model:
                return default_model
            return ""

        if default_model:
            return default_model

        return ""
