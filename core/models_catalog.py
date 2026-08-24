"""
AI Model Catalog and Context Limit Manager for Johnston.
Fetches model context limits, reasoning capabilities, and pricing dynamically
from models.dev and OpenRouter catalog APIs with local cache fallbacks.
"""

import asyncio
import logging
import os
import time
from collections import OrderedDict
from typing import Any, Dict, Iterable, Optional, Set

import httpx

from core.domain.defaults.config import DEFAULT_CONTEXT_LIMIT
from core.domain.policies.model_catalog_policy import (
    _RE_FUZZY_STRIP,
    _RE_TOKEN_SPLIT,
    format_context_tokens,
)
from core.infrastructure.adapters.models_source import (
    MODELS_DEV_URL,
    OPENROUTER_MODELS_URL,
    extract_context_length,
    extract_provider_def,
)
from core.infrastructure.platform.paths import CONFIG_DIR
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(CONFIG_DIR, "cache", "models_catalog_cache.json")
CACHE_TTL = 86400  # 24 hours

# Upper bound on the in-memory model-match cache to prevent unbounded growth.
_MATCH_CACHE_MAX = 1000


def _get_match(cache: "OrderedDict", key: tuple):
    """Fetch a (key)->value match from an LRU cache without storing misses."""
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    return None


_json_read_cache: Dict[str, tuple] = {}


def invalidate_json_read_cache(path: Optional[str] = None) -> None:
    """Invalidate cached JSON file entries."""
    if path is None:
        _json_read_cache.clear()
    else:
        _json_read_cache.pop(path, None)


def cached_json_read(path: str, default: Any = None) -> Any:
    """Reads a JSON file, returning a cache value when the file mtime is unchanged."""
    if not os.path.exists(path):
        _json_read_cache.pop(path, None)
        return default
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    cached = _json_read_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    data = read_json(path, default)
    _json_read_cache[path] = (mtime, data)
    return data


def _set_match(cache: "OrderedDict", key: tuple, value: str) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _MATCH_CACHE_MAX:
        cache.popitem(last=False)


class ModelsCatalog:
    def __init__(self):
        self._limits: Dict[str, int] = {}
        self._names: Dict[str, str] = {}
        self._pricing: Dict[str, Dict[str, float]] = {}
        self._providers: Dict[str, Dict[str, Any]] = {}
        self._match_cache: "OrderedDict" = OrderedDict()
        self._updated_at: float = 0.0
        self._client: Optional[httpx.AsyncClient] = None

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

    def load_cache(self) -> bool:
        data = read_json(CACHE_FILE)
        if data and isinstance(data, dict):
            self._limits = data.get("model_limits", {})
            self._names = data.get("model_names", {})
            self._pricing = data.get("model_pricing", {})
            self._providers = data.get("providers", {})
            self._updated_at = float(data.get("updated_at", 0.0))
            return True
        return False

    def save_cache(
        self,
        model_limits: Dict[str, int] = None,
        model_names: Dict[str, str] = None,
        model_pricing: Dict[str, Dict[str, float]] = None,
        providers: Dict[str, Dict[str, Any]] = None,
    ):
        try:
            now = time.time()
            self._updated_at = now
            payload = {
                "updated_at": now,
                "model_limits": model_limits if model_limits is not None else self._limits,
                "model_names": model_names if model_names is not None else self._names,
                "model_pricing": model_pricing if model_pricing is not None else self._pricing,
                "providers": providers if providers is not None else self._providers,
            }
            atomic_write_json(CACHE_FILE, payload, indent=2)
        except Exception as e:
            logger.warning("Error saving models catalog cache: %s", e)

    async def refresh(self, force: bool = False, max_age: float = CACHE_TTL) -> Dict[str, int]:
        if not force and self._limits and (time.time() - getattr(self, "_updated_at", 0.0) < max_age):
            return self._limits

        model_limits: Dict[str, int] = {}
        model_names: Dict[str, str] = {}
        model_pricing: Dict[str, Dict[str, float]] = {}
        provider_catalog: Dict[str, Dict[str, Any]] = {}

        try:
            client = self.get_client()
            mdev_res, openrouter_res = await asyncio.gather(
                client.get(MODELS_DEV_URL, timeout=10),
                client.get(OPENROUTER_MODELS_URL, timeout=10),
                return_exceptions=True,
            )

            # 1. Parse models.dev response
            if isinstance(mdev_res, httpx.Response) and mdev_res.status_code == 200:
                try:
                    mdev_data = mdev_res.json()
                    if isinstance(mdev_data, dict):
                        for prov_key, prov_info in mdev_data.items():
                            if not isinstance(prov_info, dict):
                                continue
                            pdef = extract_provider_def(prov_key, prov_info)
                            if pdef:
                                provider_catalog[prov_key] = pdef
                            models_dict = prov_info.get("models", {})
                            if not isinstance(models_dict, dict):
                                continue
                            for m_key, m_info in models_dict.items():
                                if not isinstance(m_info, dict):
                                    continue
                                full_id = f"{prov_key}/{m_key}"
                                alias_id = m_key

                                raw_name = m_info.get("name", m_key)
                                model_names[full_id] = raw_name
                                model_names[alias_id] = raw_name

                                limits_info = m_info.get("limit", {})
                                if isinstance(limits_info, dict):
                                    ctx = limits_info.get("context")
                                    if ctx and isinstance(ctx, (int, float)):
                                        model_limits[full_id] = int(ctx)
                                        model_limits[alias_id] = int(ctx)

                                cost_info = m_info.get("cost", {})
                                if isinstance(cost_info, dict):
                                    p_in = float(cost_info.get("input") or 0.0)
                                    p_out = float(cost_info.get("output") or 0.0)
                                    p_cr = float(cost_info.get("cache_read") or 0.0)
                                    p_cw = float(cost_info.get("cache_write") or 0.0)
                                    # Convert 1M token costs to per-token if > 0.01
                                    if p_in > 0.01:
                                        p_in /= 1_000_000.0
                                    if p_out > 0.01:
                                        p_out /= 1_000_000.0
                                    if p_cr > 0.01:
                                        p_cr /= 1_000_000.0
                                    if p_cw > 0.01:
                                        p_cw /= 1_000_000.0
                                    if p_in > 0 or p_out > 0 or p_cr > 0 or p_cw > 0:
                                        pricing_item: Dict[str, float] = {"prompt": p_in, "completion": p_out}
                                        if p_cr > 0:
                                            pricing_item["cache_read"] = p_cr
                                        if p_cw > 0:
                                            pricing_item["cache_write"] = p_cw
                                        model_pricing[full_id] = pricing_item
                                        model_pricing[alias_id] = pricing_item
                except Exception as e:
                    logger.warning("Error parsing models.dev response: %s", e)

            # 2. Parse OpenRouter response
            if isinstance(openrouter_res, httpx.Response) and openrouter_res.status_code == 200:
                try:
                    or_data = openrouter_res.json()
                    for m in or_data.get("data", []):
                        if isinstance(m, dict) and "id" in m:
                            m_id = m["id"]
                            short_id = m_id.split("/")[-1].lower()
                            raw_name = m.get("name", "")
                            clean_name = raw_name.split(": ", 1)[-1] if ": " in raw_name else raw_name
                            if clean_name:
                                model_names.setdefault(m_id, clean_name)
                                model_names.setdefault(short_id, clean_name)

                            ctx = extract_context_length(m)
                            if ctx:
                                model_limits.setdefault(m_id, ctx)
                                model_limits.setdefault(short_id, ctx)

                            pricing_raw = m.get("pricing") if isinstance(m.get("pricing"), dict) else {}
                            p_prompt = float(pricing_raw.get("prompt") or 0.0)
                            p_comp = float(pricing_raw.get("completion") or 0.0)
                            p_cr = float(pricing_raw.get("input_cache_read") or pricing_raw.get("cache_read") or 0.0)
                            p_cw = float(pricing_raw.get("input_cache_write") or pricing_raw.get("cache_write") or 0.0)
                            if p_prompt > 0 or p_comp > 0 or p_cr > 0 or p_cw > 0:
                                pricing_item = {"prompt": p_prompt, "completion": p_comp}
                                if p_cr > 0:
                                    pricing_item["cache_read"] = p_cr
                                if p_cw > 0:
                                    pricing_item["cache_write"] = p_cw
                                model_pricing.setdefault(m_id, pricing_item)
                                model_pricing.setdefault(short_id, pricing_item)
                except Exception as e:
                    logger.warning("Error parsing OpenRouter response: %s", e)

            self._limits = model_limits
            self._names = model_names
            self._pricing = model_pricing
            if provider_catalog:
                self._providers = provider_catalog
            self._match_cache.clear()

            self.save_cache()
        except Exception as e:
            logger.warning("Error fetching models catalog: %s", e)
        return self._limits

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
        )

    def _resolve_catalog_key(
        self, provider_id: str, model_id: str, search_space: Iterable[str] = None, tag: str = ""
    ) -> str:
        if not model_id:
            return ""

        space_keys = set(search_space) if search_space is not None else self._get_all_catalog_keys()
        if not space_keys:
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
        else:
            space_obj = getattr(search_space, "__self__", search_space)
            space_tag = id(space_obj) if space_obj is not None else id(self._limits)

        cache_key = (provider_id, model_id, space_tag, len(space_keys))
        cached = _get_match(self._match_cache, cache_key)
        if cached is not None:
            return cached

        # Stage 1: Exact match
        if model_id in space_keys:
            _set_match(self._match_cache, cache_key, model_id)
            return model_id

        # Stage 2: Scoped match
        scoped_id = f"{provider_id}/{model_id}" if provider_id else ""
        if scoped_id and scoped_id in space_keys:
            _set_match(self._match_cache, cache_key, scoped_id)
            return scoped_id

        # Stage 3: Base slug match (O(1) dictionary lookup)
        m_base = model_id.split("/")[-1].split(":")[0].lower()
        if not hasattr(self, "_slug_maps"):
            self._slug_maps = {}

        slug_key = space_tag
        if slug_key not in self._slug_maps or self._slug_maps[slug_key][0] != len(space_keys):
            slug_map = {}
            for k in space_keys:
                kb = k.split("/")[-1].split(":")[0].lower()
                if kb not in slug_map:
                    slug_map[kb] = k
            self._slug_maps[slug_key] = (len(space_keys), slug_map)

        slug_map = self._slug_maps[slug_key][1]
        if m_base in slug_map:
            match = slug_map[m_base]
            _set_match(self._match_cache, cache_key, match)
            return match

        # Stage 4: Fuzzy & Substring Token Match (for local HF/MLX/GGUF models)
        cleaned = _RE_FUZZY_STRIP.sub("", m_base)
        tokens = set(_RE_TOKEN_SPLIT.findall(cleaned))
        ignored_tokens = {
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
        }
        # NOTE: "free" stays ignored (tier markers are noise), but "preview" is
        # NOT ignored: variant/date tokens like "preview" distinguish distinct
        # catalog entries, and dropping it let unrelated models fuzzy-match each
        # other (e.g. x-preview-f-free -> zai/glm-4.5-x borrowing paid pricing).
        clean_tokens = tokens - ignored_tokens
        query_digits = {t for t in clean_tokens if t.isdigit()}

        if len(clean_tokens) >= 2:
            best_match = ""
            best_score = 0
            for k in space_keys:
                k_base = k.split("/")[-1].split(":")[0].lower()
                k_tokens = set(_RE_TOKEN_SPLIT.findall(k_base)) - ignored_tokens
                k_digits = {t for t in k_tokens if t.isdigit()}

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

        return DEFAULT_CONTEXT_LIMIT

    def update_model_names(self, names: Dict[str, str]) -> None:
        """Merges provider-discovered model display names into the catalog (public API)."""
        if not names:
            return
        self._names.update(names)
        self._match_cache.clear()

    def get_model_display_name(self, provider_id: str, model_id: str) -> str:
        if not model_id:
            return ""
        if not self._names and not self._limits:
            self.load_cache()

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


catalog = ModelsCatalog()


def get_context_window(provider_id: str, model_id: str) -> str:
    limit = catalog.get_context_limit(provider_id, model_id)
    return format_context_tokens(limit)
