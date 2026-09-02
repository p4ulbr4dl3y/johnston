"""
AI Model Catalog and Context Limit Manager for Johnston.
Fetches model context limits, reasoning capabilities, and pricing dynamically
from models.dev and OpenRouter catalog APIs with local cache fallbacks.
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, FrozenSet, Optional, Set

import httpx

from core.domain.defaults.config import DEFAULT_CATALOG_CACHE_TTL, DEFAULT_CONTEXT_LIMIT
from core.domain.entities.models import ModelPricing, ModelSpec
from core.domain.policies.model_catalog_policy import (
    _RE_FUZZY_STRIP,
    _RE_TOKEN_SPLIT,
    format_context_tokens,
)
from core.infrastructure.adapters.models_fetcher import fetch_catalog_endpoints
from core.infrastructure.platform.paths import CONFIG_DIR
from core.infrastructure.platform.platform_utils import (
    atomic_write_json,
    cached_json_read,
    read_json,
)
from core.infrastructure.runtime.lru import LruCache

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(CONFIG_DIR, "cache", "models_catalog_cache.json")
CACHE_TTL = DEFAULT_CATALOG_CACHE_TTL

# Upper bound on the in-memory model-match cache to prevent unbounded growth.
_MATCH_CACHE_MAX = 1000

_IGNORED_TOKENS: FrozenSet[str] = frozenset({
    "it",
    "mlx",
    "gguf",
    "quant",
    "4bit",
    "8bit",
    "16bit",
    "fp16",
    "fp32",
    "v1",
    "v2",
    "vision",
    "model",
    "chat",
    "instruct",
    "text",
    "api",
    "base",
    "free",
    "pro",
    "flash",
    "mini",
    "small",
    "large",
    "turbo",
    "latest",
    "non",
    "dummy",
    "unknown",
})


def _get_match(cache: "LruCache", key: tuple):
    """Fetch a (key)->value match from an LRU cache without storing misses."""
    return cache.get(key)


def _set_match(cache: "LruCache", key: tuple, value: str) -> None:
    cache.put(key, value)


class ModelsCatalog:
    def __init__(self):
        self._limits: Dict[str, int] = {}
        self._names: Dict[str, str] = {}
        self._pricing: Dict[str, Dict[str, float]] = {}
        self._modalities: Dict[str, list[str]] = {}
        self._providers: Dict[str, Dict[str, Any]] = {}
        self._match_cache: "LruCache" = LruCache(_MATCH_CACHE_MAX)
        self._display_name_cache: "LruCache" = LruCache(_MATCH_CACHE_MAX)
        self._vision_cache: "LruCache" = LruCache(_MATCH_CACHE_MAX)
        self._updated_at: float = 0.0
        self._client: Optional[httpx.AsyncClient] = None

    def _clear_internal_caches(self) -> None:
        self._match_cache.clear()
        self._display_name_cache.clear()
        self._vision_cache.clear()
        if hasattr(self, "_slug_maps"):
            self._slug_maps.clear()
        if hasattr(self, "_token_maps"):
            self._token_maps.clear()

    def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50)
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def save_cache_async(
        self,
        model_limits: Dict[str, int] = None,
        model_names: Dict[str, str] = None,
        model_pricing: Dict[str, Dict[str, float]] = None,
        model_modalities: Dict[str, list[str]] = None,
        providers: Dict[str, Dict[str, Any]] = None,
    ) -> None:
        await asyncio.to_thread(
            self.save_cache,
            model_limits=model_limits,
            model_names=model_names,
            model_pricing=model_pricing,
            model_modalities=model_modalities,
            providers=providers,
        )

    def load_cache(self) -> bool:
        data = read_json(CACHE_FILE)
        if data and isinstance(data, dict):
            self._limits = data.get("model_limits", {})
            self._names = data.get("model_names", {})
            self._pricing = data.get("model_pricing", {})
            self._modalities = data.get("model_modalities", {})
            self._providers = data.get("providers", {})
            self._updated_at = float(data.get("updated_at", 0.0))
            self._clear_internal_caches()
            return True
        return False

    def save_cache(
        self,
        model_limits: Dict[str, int] = None,
        model_names: Dict[str, str] = None,
        model_pricing: Dict[str, Dict[str, float]] = None,
        model_modalities: Dict[str, list[str]] = None,
        providers: Dict[str, Dict[str, Any]] = None,
    ):
        try:
            if not self._limits and not self._names:
                self.load_cache()
            now = time.time()
            self._updated_at = now
            payload = {
                "updated_at": now,
                "model_limits": model_limits if model_limits is not None else self._limits,
                "model_names": model_names if model_names is not None else self._names,
                "model_pricing": model_pricing if model_pricing is not None else self._pricing,
                "model_modalities": model_modalities if model_modalities is not None else self._modalities,
                "providers": providers if providers is not None else self._providers,
            }
            atomic_write_json(CACHE_FILE, payload, indent=2)
        except Exception as e:
            logger.warning("Error saving models catalog cache: %s", e)

    async def refresh(self, force: bool = False, max_age: float | None = None) -> Dict[str, int]:
        if max_age is None:
            try:
                from core.infrastructure.config.settings import get_settings

                max_age = get_settings().llm.catalog_cache_ttl
            except Exception:
                max_age = CACHE_TTL
        if not force and self._limits and (time.time() - getattr(self, "_updated_at", 0.0) < max_age):
            return self._limits

        try:
            client = self.get_client()
            (
                model_limits,
                model_names,
                model_pricing,
                model_modalities,
                provider_catalog,
            ) = await fetch_catalog_endpoints(client)

            self._limits = model_limits
            self._names = model_names
            self._pricing = model_pricing
            self._modalities = model_modalities
            if provider_catalog:
                self._providers = provider_catalog
            self._clear_internal_caches()

            await self.save_cache_async()
        except Exception as e:
            logger.warning("Error fetching models catalog: %s", e)
        return self._limits

    def get_model_spec(self, provider_id: str, model_id: str) -> ModelSpec:
        """Returns a structured ModelSpec domain entity for a given model."""
        return ModelSpec(
            id=model_id,
            name=self.get_model_display_name(provider_id, model_id),
            context_limit=self.get_context_limit(provider_id, model_id),
            pricing=ModelPricing.from_dict(self.get_model_pricing(provider_id, model_id)),
            modalities=self.get_model_modalities(provider_id, model_id),
        )

    def get_discovered_providers(self) -> Dict[str, Dict[str, Any]]:
        """Returns dynamically discovered provider definitions from models.dev."""
        if not self._providers:
            self.load_cache()
        return dict(self._providers)

    def get_catalog_provider(self, provider_key: str) -> Optional[Dict[str, Any]]:
        """Returns a provider definition discovered from models.dev by its key."""
        if not self._providers:
            self.load_cache()
        return self._providers.get(provider_key)

    def _get_all_catalog_keys(self) -> Set[str]:
        return set().union(
            self._limits,
            self._names,
            self._pricing,
            self._modalities,
        )

    def _resolve_catalog_key(
        self, provider_id: str, model_id: str, search_space: Any = None, tag: str = ""
    ) -> str:
        if not model_id:
            return ""

        space_obj = search_space if search_space is not None else self._get_all_catalog_keys()
        if not space_obj:
            return ""

        if tag:
            space_tag = tag
        elif search_space is self._limits or (
            hasattr(search_space, "__self__") and search_space.__self__ is self._limits
        ):
            space_tag = "limits"
        elif search_space is self._names or (
            hasattr(search_space, "__self__") and search_space.__self__ is self._names
        ):
            space_tag = "names"
        elif search_space is self._pricing or (
            hasattr(search_space, "__self__") and search_space.__self__ is self._pricing
        ):
            space_tag = "pricing"
        elif search_space is self._modalities or (
            hasattr(search_space, "__self__") and search_space.__self__ is self._modalities
        ):
            space_tag = "modalities"
        else:
            space_target = getattr(search_space, "__self__", search_space)
            space_tag = id(space_target) if space_target is not None else id(self._limits)

        space_len = len(space_obj)
        cache_key = (provider_id, model_id, space_tag, space_len)
        cached = _get_match(self._match_cache, cache_key)
        if cached is not None:
            return cached

        # Stage 1: Exact match
        if model_id in space_obj:
            _set_match(self._match_cache, cache_key, model_id)
            return model_id

        # Stage 2: Scoped match
        scoped_id = f"{provider_id}/{model_id}" if provider_id else ""
        if scoped_id and scoped_id in space_obj:
            _set_match(self._match_cache, cache_key, scoped_id)
            return scoped_id

        # Stage 3: Base slug match (O(1) dictionary lookup)
        m_base = model_id.split("/")[-1].split(":")[0].lower()
        if not hasattr(self, "_slug_maps"):
            self._slug_maps = {}

        slug_key = space_tag
        if slug_key not in self._slug_maps or self._slug_maps[slug_key][0] != space_len:
            slug_map = {}
            for k in space_obj:
                kb = k.split("/")[-1].split(":")[0].lower()
                if kb not in slug_map:
                    slug_map[kb] = k
            self._slug_maps[slug_key] = (space_len, slug_map)

        slug_map = self._slug_maps[slug_key][1]
        if m_base in slug_map:
            match = slug_map[m_base]
            _set_match(self._match_cache, cache_key, match)
            return match

        # Stage 4: Fuzzy & Substring Token Match (for local HF/MLX/GGUF models)
        cleaned = _RE_FUZZY_STRIP.sub("", m_base)
        tokens = set(_RE_TOKEN_SPLIT.findall(cleaned))
        clean_tokens = tokens - _IGNORED_TOKENS
        query_digits = {t for t in clean_tokens if t.isdigit()}

        if len(clean_tokens) >= 2:
            if not hasattr(self, "_token_maps"):
                self._token_maps = {}

            if slug_key not in self._token_maps or self._token_maps[slug_key][0] != space_len:
                token_entries = []
                for k in space_obj:
                    k_base = k.split("/")[-1].split(":")[0].lower()
                    k_tokens = set(_RE_TOKEN_SPLIT.findall(k_base)) - _IGNORED_TOKENS
                    k_digits = {t for t in k_tokens if t.isdigit()}
                    token_entries.append((k, k_tokens, k_digits))
                self._token_maps[slug_key] = (space_len, token_entries)

            token_entries = self._token_maps[slug_key][1]
            best_match = ""
            best_score = 0
            for k, k_tokens, k_digits in token_entries:
                # If digit version tokens conflict (e.g. gemma-4 vs gemma-2), skip candidate
                if query_digits and k_digits and query_digits != k_digits:
                    continue

                overlap = clean_tokens & k_tokens
                if overlap and (clean_tokens.issubset(k_tokens) or len(overlap) >= len(clean_tokens) - 1):
                    score = len(overlap)
                    if score > best_score:
                        best_score = score
                        best_match = k
            if best_match:
                _set_match(self._match_cache, cache_key, best_match)
                return best_match

        _set_match(self._match_cache, cache_key, "")
        return ""

    def get_context_limit(self, provider_id: str, model_id: str) -> int:
        if not self._limits and not self._names:
            self.load_cache()

        resolved = self._resolve_catalog_key(provider_id, model_id, self._limits, tag="limits")
        if resolved and resolved in self._limits:
            val = self._limits[resolved]
            if isinstance(val, int) and not isinstance(val, bool):
                return val

        if provider_id:
            prov_cache = os.path.join(CONFIG_DIR, "cache", f"models_{provider_id}.json")
            if os.path.exists(prov_cache):
                cdata = cached_json_read(prov_cache, {})
                if isinstance(cdata, dict):
                    lims = cdata.get("model_limits", {})
                    if lims:
                        res_prov = self._resolve_catalog_key(
                            provider_id, model_id, lims, tag=f"prov_{provider_id}_limits"
                        )
                        if res_prov and res_prov in lims:
                            val = lims[res_prov]
                            if isinstance(val, int) and not isinstance(val, bool):
                                return val

        # Fall back to the user-configurable context limit so the compaction
        # threshold and token-window scaling honor config.json/`JOHNSTON_CONTEXT_LIMIT`.
        try:
            from core.infrastructure.config.settings import get_settings

            configured = get_settings().llm.context_limit
            if isinstance(configured, int) and not isinstance(configured, bool) and configured > 0:
                return configured
        except Exception:
            pass
        return DEFAULT_CONTEXT_LIMIT

    def update_model_names(self, names: Dict[str, str]) -> None:
        """Merges provider-discovered model display names into the catalog (public API)."""
        if not names:
            return
        self._names.update(names)
        self._clear_internal_caches()

    def get_model_display_name(self, provider_id: str, model_id: str) -> str:
        if not model_id:
            return ""
        if not self._names and not self._limits:
            self.load_cache()

        cache_key = (provider_id, model_id, len(self._names))
        cached = _get_match(self._display_name_cache, cache_key)
        if cached is not None:
            return cached

        suffix_tag = ""
        if ":" in model_id:
            suffix_raw = model_id.split(":", 1)[1]
            if suffix_raw and not suffix_raw.startswith("//"):
                suffix_tag = suffix_raw.strip().capitalize()

        resolved = self._resolve_catalog_key(provider_id, model_id, self._names, tag="names")
        if resolved and resolved in self._names:
            name = self._names[resolved]
            if ": " in name:
                name = name.split(": ", 1)[-1]
            if suffix_tag and f"({suffix_tag})" not in name and suffix_tag.lower() not in name.lower():
                name += f" ({suffix_tag})"
            _set_match(self._display_name_cache, cache_key, name)
            return name

        base_raw = model_id.split("/")[-1].split(":")[0]
        parts = base_raw.replace("_", "-").split("-")

        formatted = []
        for p in parts:
            p_low = p.lower()
            if p_low == "gpt":
                formatted.append("GPT")
            elif p_low in ("ai", "llm", "db", "ui", "api", "sql", "json"):
                formatted.append(p.upper())
            elif p.isdigit() or len(p) <= 1:
                formatted.append(p)
            else:
                formatted.append(p.capitalize())

        res = " ".join(formatted)
        if suffix_tag and f"({suffix_tag})" not in res:
            res += f" ({suffix_tag})"
        _set_match(self._display_name_cache, cache_key, res)
        return res

    def get_model_pricing(self, provider_id: str, model_id: str) -> Dict[str, float]:
        if not self._pricing and not self._limits:
            self.load_cache()

        resolved = self._resolve_catalog_key(provider_id, model_id, self._pricing, tag="pricing")
        if resolved and resolved in self._pricing:
            return self._pricing[resolved]

        return {"prompt": 0.0, "completion": 0.0}

    @staticmethod
    def is_free_model(model_id: Any) -> bool:
        """True when the model id itself advertises a free tier.

        Single source of truth for free-model detection: usage accumulation
        (BaseAgent._accumulate_usage) and display-time estimates must agree,
        otherwise the UI invents money for models that were correctly priced
        at zero.
        """
        m = str(model_id or "").lower()
        if not m:
            return False
        return ":free" in m or "-free" in m or "/free" in m or m.endswith("free")

    def estimate_cost_from_totals(self, provider_id: str, model_id: str, total_tokens: int) -> float:
        """Rough display-time USD estimate for a token total at catalog rates.

        Conservative by design: returns 0.0 for free models and whenever pricing
        cannot be pinned to the model's own base slug (exact/scoped/slug match
        only — never the Stage-4 fuzzy match), so an unknown or free model never
        borrows a paid sibling's rates. Half of the tokens are billed at input
        rate, half at output rate — same heuristic as session-level estimation.
        """
        if not total_tokens or total_tokens <= 0:
            return 0.0
        if self.is_free_model(model_id):
            return 0.0

        resolved = self._resolve_catalog_key(provider_id, model_id, self._pricing, tag="pricing")
        if not resolved or resolved not in self._pricing:
            return 0.0

        m_base = str(model_id).split("/")[-1].split(":")[0].lower()
        r_base = resolved.split("/")[-1].split(":")[0].lower()
        if r_base != m_base:
            return 0.0

        pricing = self._pricing[resolved]
        half = total_tokens / 2.0
        return half * pricing.get("prompt", 0.0) + half * pricing.get("completion", 0.0)

    def has_vision(self, provider_id: str, model_id: str) -> bool:
        """Returns True if the model supports image/vision input."""
        if not model_id:
            return False
        if not self._modalities and not self._limits:
            self.load_cache()

        cache_key = (provider_id, model_id, len(self._modalities))
        cached = _get_match(self._vision_cache, cache_key)
        if cached is not None:
            return cached

        resolved = self._resolve_catalog_key(provider_id, model_id, self._modalities, tag="modalities")
        if resolved and resolved in self._modalities:
            mods = self._modalities[resolved]
            if isinstance(mods, (list, tuple, set)):
                res = "image" in mods or "vision" in mods
                _set_match(self._vision_cache, cache_key, res)
                return res

        _set_match(self._vision_cache, cache_key, False)
        return False

    def get_model_modalities(self, provider_id: str, model_id: str) -> list[str]:
        """Returns input modalities supported by the model (e.g. ['text', 'image'])."""
        if not model_id:
            return ["text"]
        if not self._modalities and not self._limits:
            self.load_cache()

        resolved = self._resolve_catalog_key(provider_id, model_id, self._modalities, tag="modalities")
        if resolved and resolved in self._modalities:
            mods = self._modalities[resolved]
            if isinstance(mods, list):
                return list(mods)
        if self.has_vision(provider_id, model_id):
            return ["text", "image"]
        return ["text"]


catalog = ModelsCatalog()


def get_context_window(provider_id: str, model_id: str) -> str:
    limit = catalog.get_context_limit(provider_id, model_id)
    return format_context_tokens(limit)
