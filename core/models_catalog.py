"""
AI Model Catalog and Context Limit Manager for Johnston.
Fetches model context limits, reasoning capabilities, and pricing dynamically
from models.dev and OpenRouter catalog APIs with local cache fallbacks.
"""

import asyncio
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Dict, Iterable, List, Set

import httpx

from core.config import CONFIG_DIR
from core.defaults.config import DEFAULT_CONTEXT_LIMIT
from core.platform_utils import atomic_write_json, read_json

logger = logging.getLogger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

CACHE_FILE = os.path.join(CONFIG_DIR, "cache", "models_catalog_cache.json")
CACHE_TTL = 86400  # 24 hours

# Precompiled regexes (avoids recompilation on every _resolve_catalog_key call).
_RE_FUZZY_STRIP = re.compile(r"(?i)[-_](mlx|4bit|8bit|16bit|gguf|q\d_[k0-9_]+|fp\d+|instruct|it|v\d+[\d\.]*)")
_RE_TOKEN_SPLIT = re.compile(r"[a-z0-9]+")

# Upper bound on the in-memory model-match cache to prevent unbounded growth.
_MATCH_CACHE_MAX = 1000


def _get_match(cache: "OrderedDict", key: tuple):
    """Fetch a (key)->value match from an LRU cache without storing misses."""
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    return None


def _set_match(cache: "OrderedDict", key: tuple, value: str) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _MATCH_CACHE_MAX:
        cache.popitem(last=False)


def format_context_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        val = tokens / 1_000_000
        if val % 1 == 0:
            return f"{int(val)}M"
        if round(val, 1) == 1.0:
            return "1M"
        return f"{val:.1f}M"
    elif tokens >= 1_000:
        val = tokens / 1_000
        if val >= 100 or val % 1 == 0:
            return f"{int(val)}k"
        return f"{val:.1f}k"
    return str(tokens)


class ModelsCatalog:
    def __init__(self):
        self._limits: Dict[str, int] = {}
        self._output_limits: Dict[str, int] = {}
        self._reasoning: List[str] = []
        self._open_weights: List[str] = []
        self._names: Dict[str, str] = {}
        self._descriptions: Dict[str, str] = {}
        self._pricing: Dict[str, Dict[str, float]] = {}
        self._match_cache: "OrderedDict" = OrderedDict()
        self._updated_at: float = 0.0
        # Provider-cache JSON read cache: path -> (mtime, parsed dict). Avoids a
        # disk read on every get_context_limit miss; invalidated by mtime change.
        self._prov_cache: Dict[str, tuple] = {}
        self.load_cache()

    def load_cache(self) -> bool:
        data = read_json(CACHE_FILE)
        if data and isinstance(data, dict):
            self._limits = data.get("model_limits", {})
            self._output_limits = data.get("output_limits", {})
            self._reasoning = data.get("reasoning_models", [])
            self._open_weights = data.get("open_weights_models", [])
            self._names = data.get("model_names", {})
            self._descriptions = data.get("model_descriptions", {})
            self._pricing = data.get("model_pricing", {})
            self._updated_at = float(data.get("updated_at", 0.0))
            return True
        return False

    def save_cache(
        self,
        model_limits: Dict[str, int] = None,
        model_names: Dict[str, str] = None,
        model_pricing: Dict[str, Dict[str, float]] = None,
    ):
        try:
            now = time.time()
            self._updated_at = now
            payload = {
                "updated_at": now,
                "model_limits": model_limits if model_limits is not None else self._limits,
                "output_limits": self._output_limits,
                "reasoning_models": self._reasoning,
                "open_weights_models": self._open_weights,
                "model_names": model_names if model_names is not None else self._names,
                "model_descriptions": self._descriptions,
                "model_pricing": model_pricing if model_pricing is not None else self._pricing,
            }
            atomic_write_json(CACHE_FILE, payload, indent=2)
        except Exception as e:
            logger.warning("Error saving models catalog cache: %s", e)

    async def refresh(self, force: bool = False, max_age: float = CACHE_TTL) -> Dict[str, int]:
        if not force and self._limits and (time.time() - getattr(self, "_updated_at", 0.0) < max_age):
            return self._limits

        model_limits: Dict[str, int] = {}
        output_limits: Dict[str, int] = {}
        reasoning_models: List[str] = []
        open_weights_models: List[str] = []
        model_names: Dict[str, str] = {}
        model_descriptions: Dict[str, str] = {}
        model_pricing: Dict[str, Dict[str, float]] = {}

        try:
            async with httpx.AsyncClient() as client:
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

                                desc = m_info.get("description", "")
                                if desc:
                                    model_descriptions[full_id] = desc
                                    model_descriptions[alias_id] = desc

                                limits_info = m_info.get("limit", {})
                                if isinstance(limits_info, dict):
                                    ctx = limits_info.get("context")
                                    if ctx and isinstance(ctx, (int, float)):
                                        model_limits[full_id] = int(ctx)
                                        model_limits[alias_id] = int(ctx)
                                    out_len = limits_info.get("output")
                                    if out_len and isinstance(out_len, (int, float)):
                                        output_limits[full_id] = int(out_len)
                                        output_limits[alias_id] = int(out_len)

                                if m_info.get("reasoning"):
                                    reasoning_models.extend([full_id, alias_id])

                                if m_info.get("open_weights"):
                                    open_weights_models.extend([full_id, alias_id])

                                cost_info = m_info.get("cost", {})
                                if isinstance(cost_info, dict):
                                    p_in = float(cost_info.get("input") or 0.0)
                                    p_out = float(cost_info.get("output") or 0.0)
                                    # Convert 1M token costs to per-token if > 0.01
                                    if p_in > 0.01:
                                        p_in /= 1_000_000.0
                                    if p_out > 0.01:
                                        p_out /= 1_000_000.0
                                    if p_in > 0 or p_out > 0:
                                        pricing_item = {"prompt": p_in, "completion": p_out}
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

                            ctx = (
                                m.get("context_length")
                                or (m.get("top_provider", {}) or {}).get("context_length")
                                or m.get("context_window")
                            )
                            if ctx and isinstance(ctx, (int, float)):
                                model_limits.setdefault(m_id, int(ctx))
                                model_limits.setdefault(short_id, int(ctx))

                            pricing_raw = m.get("pricing") if isinstance(m.get("pricing"), dict) else {}
                            p_prompt = float(pricing_raw.get("prompt") or 0.0)
                            p_comp = float(pricing_raw.get("completion") or 0.0)
                            if p_prompt > 0 or p_comp > 0:
                                pricing_item = {"prompt": p_prompt, "completion": p_comp}
                                model_pricing.setdefault(m_id, pricing_item)
                                model_pricing.setdefault(short_id, pricing_item)
                except Exception as e:
                    logger.warning("Error parsing OpenRouter response: %s", e)

            self._limits = model_limits
            self._output_limits = output_limits
            self._reasoning = list(set(reasoning_models))
            self._open_weights = list(set(open_weights_models))
            self._names = model_names
            self._descriptions = model_descriptions
            self._pricing = model_pricing
            self._match_cache.clear()

            self.save_cache()
        except Exception as e:
            logger.warning("Error fetching models catalog: %s", e)
        return self._limits

    def _get_all_catalog_keys(self) -> Set[str]:
        return set().union(
            self._limits,
            self._names,
            self._descriptions,
            self._pricing,
            self._reasoning,
            self._open_weights,
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
        elif search_space is self._reasoning:
            space_tag = "reasoning"
        elif search_space is self._open_weights:
            space_tag = "open_weights"
        elif search_space is self._limits or (
            hasattr(search_space, "__self__") and search_space.__self__ is self._limits
        ):
            space_tag = "limits"
        elif search_space is self._names or (
            hasattr(search_space, "__self__") and search_space.__self__ is self._names
        ):
            space_tag = "names"
        elif search_space is self._descriptions or (
            hasattr(search_space, "__self__") and search_space.__self__ is self._descriptions
        ):
            space_tag = "descriptions"
        elif search_space is self._pricing or (
            hasattr(search_space, "__self__") and search_space.__self__ is self._pricing
        ):
            space_tag = "pricing"
        elif search_space is self._output_limits or (
            hasattr(search_space, "__self__") and search_space.__self__ is self._output_limits
        ):
            space_tag = "output_limits"
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
            "preview",
            "non",
            "dummy",
            "unknown",
        }
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
            return self._limits[resolved]

        if provider_id:
            prov_cache = os.path.join(CONFIG_DIR, "cache", f"models_{provider_id}.json")
            if os.path.exists(prov_cache):
                try:
                    mtime = os.path.getmtime(prov_cache)
                except OSError:
                    mtime = None
                cached = self._prov_cache.get(prov_cache)
                if cached is not None and cached[0] == mtime:
                    cdata = cached[1]
                else:
                    cdata = read_json(prov_cache, {})
                    self._prov_cache[prov_cache] = (mtime, cdata)
                if isinstance(cdata, dict):
                    lims = cdata.get("model_limits", {})
                    if lims:
                        res_prov = self._resolve_catalog_key(
                            provider_id, model_id, lims, tag=f"prov_{provider_id}_limits"
                        )
                        if res_prov and res_prov in lims:
                            return lims[res_prov]

        return DEFAULT_CONTEXT_LIMIT

    def get_model_display_name(self, provider_id: str, model_id: str) -> str:
        if not model_id:
            return ""

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


catalog = ModelsCatalog()


def get_context_window(provider_id: str, model_id: str) -> str:
    limit = catalog.get_context_limit(provider_id, model_id)
    return format_context_tokens(limit)
