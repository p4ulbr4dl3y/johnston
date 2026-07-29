"""
AI Model Catalog and Context Limit Manager for Johnston.
Fetches model context limits, vision, reasoning capabilities, and pricing dynamically
from models.dev and OpenRouter catalog APIs with local cache fallbacks.
"""
import asyncio
import json
import os
import re
import time
from typing import Dict, Iterable, List, Set, Tuple

import httpx

from core.config import CONFIG_DIR, CONFIG_FILE

MODELS_DEV_URL = "https://models.dev/api.json"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

CACHE_FILE = os.path.join(CONFIG_DIR, "cache", "models_catalog_cache.json")
CACHE_TTL = 86400  # 24 hours

DEFAULT_CONTEXT_LIMIT = 128000


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
        self._vision: List[str] = []
        self._reasoning: List[str] = []
        self._open_weights: List[str] = []
        self._user_overrides: List[str] = []
        self._names: Dict[str, str] = {}
        self._descriptions: Dict[str, str] = {}
        self._pricing: Dict[str, Dict[str, float]] = {}
        self._fallback_vision_provider: str = ""
        self._fallback_vision_model: str = ""
        self._fallback_vision_explicit: bool = False
        self._match_cache: Dict[str, str] = {}
        self.load_cache()

    def _trigger_background_refresh(self):
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                task = loop.create_task(self.refresh())
                def _log_exc(t):
                    try:
                        t.result()
                    except Exception as e:
                        print(f"ModelsCatalog background refresh error: {e}")
                task.add_done_callback(_log_exc)
        except RuntimeError:
            pass

    def load_cache(self) -> bool:
        loaded = False
        target_file = CACHE_FILE if os.path.exists(CACHE_FILE) else None
        if target_file:
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._limits = data.get("model_limits", {})
                    self._output_limits = data.get("output_limits", {})
                    self._user_overrides = data.get("user_vision_overrides", [])
                    self._native_vision = data.get("vision_models", [])
                    self._vision = list(set(self._native_vision + self._user_overrides))
                    self._reasoning = data.get("reasoning_models", [])
                    self._open_weights = data.get("open_weights_models", [])
                    self._names = data.get("model_names", {})
                    self._descriptions = data.get("model_descriptions", {})
                    self._pricing = data.get("model_pricing", {})
                    self._fallback_vision_provider = data.get("fallback_vision_provider", "")
                    self._fallback_vision_model = data.get("fallback_vision_model", "")
                    self._fallback_vision_explicit = data.get("fallback_vision_explicit", False)
                loaded = True
            except Exception:
                pass

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                    if isinstance(cfg_data, dict):
                        fb_m = cfg_data.get("fallback_vision_model")
                        if fb_m:
                            self._fallback_vision_model = fb_m
                            self._fallback_vision_provider = cfg_data.get("fallback_vision_provider", "")
                            if "fallback_vision_explicit" in cfg_data:
                                self._fallback_vision_explicit = bool(cfg_data["fallback_vision_explicit"])
            except Exception:
                pass

        return loaded

    def save_cache(
        self,
        model_limits: Dict[str, int] = None,
        vision_models: List[str] = None,
        model_names: Dict[str, str] = None,
        model_pricing: Dict[str, Dict[str, float]] = None,
    ):
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        temp_file = CACHE_FILE + ".tmp"
        try:
            payload = {
                "updated_at": time.time(),
                "model_limits": model_limits if model_limits is not None else self._limits,
                "output_limits": self._output_limits,
                "vision_models": vision_models if vision_models is not None else getattr(self, "_native_vision", self._vision),
                "reasoning_models": self._reasoning,
                "open_weights_models": self._open_weights,
                "user_vision_overrides": self._user_overrides,
                "fallback_vision_provider": self._fallback_vision_provider,
                "fallback_vision_model": self._fallback_vision_model,
                "fallback_vision_explicit": self._fallback_vision_explicit,
                "model_names": model_names if model_names is not None else self._names,
                "model_descriptions": self._descriptions,
                "model_pricing": model_pricing if model_pricing is not None else self._pricing,
            }
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, CACHE_FILE)
        except Exception as e:
            print(f"Error saving models catalog cache: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    async def refresh(self) -> Dict[str, int]:
        model_limits: Dict[str, int] = {}
        output_limits: Dict[str, int] = {}
        vision_models: List[str] = []
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

                                modalities = m_info.get("modalities", {})
                                input_mods = modalities.get("input", []) if isinstance(modalities, dict) else []
                                if any(x in input_mods for x in ("image", "vision", "video")):
                                    vision_models.extend([full_id, alias_id])

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
                    print(f"Error parsing models.dev response: {e}")

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

                            arch = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
                            input_mods = (
                                arch.get("input_modalities")
                                or m.get("input_modalities")
                                or m.get("modalities")
                                or []
                            )
                            if any(x in input_mods for x in ("image", "vision")):
                                vision_models.extend([m_id, short_id])

                            pricing_raw = m.get("pricing") if isinstance(m.get("pricing"), dict) else {}
                            p_prompt = float(pricing_raw.get("prompt") or 0.0)
                            p_comp = float(pricing_raw.get("completion") or 0.0)
                            if p_prompt > 0 or p_comp > 0:
                                pricing_item = {"prompt": p_prompt, "completion": p_comp}
                                model_pricing.setdefault(m_id, pricing_item)
                                model_pricing.setdefault(short_id, pricing_item)
                except Exception as e:
                    print(f"Error parsing OpenRouter response: {e}")

            self._limits = model_limits
            self._output_limits = output_limits
            self._native_vision = list(set(vision_models))

            # Merge with user vision overrides
            merged_vision = list(vision_models)
            for ov in self._user_overrides:
                if ov not in merged_vision:
                    merged_vision.append(ov)

            self._vision = list(set(merged_vision))
            self._reasoning = list(set(reasoning_models))
            self._open_weights = list(set(open_weights_models))
            self._names = model_names
            self._descriptions = model_descriptions
            self._pricing = model_pricing
            self._match_cache.clear()

            self.save_cache()
        except Exception as e:
            print(f"Error fetching models catalog: {e}")
        return self._limits

    def _get_all_catalog_keys(self) -> Set[str]:
        return set().union(
            self._limits,
            self._output_limits,
            self._names,
            self._descriptions,
            self._pricing,
            self._vision,
            self._reasoning,
            self._open_weights,
        )

    def _resolve_catalog_key(self, provider_id: str, model_id: str, search_space: Iterable[str] = None, tag: str = "") -> str:
        if not model_id:
            return ""

        space_keys = set(search_space) if search_space is not None else self._get_all_catalog_keys()
        if not space_keys:
            return ""

        if tag:
            space_tag = tag
        elif search_space is self._vision:
            space_tag = "vision"
        elif search_space is self._reasoning:
            space_tag = "reasoning"
        elif search_space is self._open_weights:
            space_tag = "open_weights"
        elif search_space is self._limits or (hasattr(search_space, "__self__") and search_space.__self__ is self._limits):
            space_tag = "limits"
        elif search_space is self._names or (hasattr(search_space, "__self__") and search_space.__self__ is self._names):
            space_tag = "names"
        elif search_space is self._descriptions or (hasattr(search_space, "__self__") and search_space.__self__ is self._descriptions):
            space_tag = "descriptions"
        elif search_space is self._pricing or (hasattr(search_space, "__self__") and search_space.__self__ is self._pricing):
            space_tag = "pricing"
        elif search_space is self._output_limits or (hasattr(search_space, "__self__") and search_space.__self__ is self._output_limits):
            space_tag = "output_limits"
        else:
            space_obj = getattr(search_space, "__self__", search_space)
            space_tag = id(space_obj) if space_obj is not None else id(self._limits)

        cache_key = (provider_id, model_id, space_tag, len(space_keys))
        if cache_key in self._match_cache:
            return self._match_cache[cache_key]

        # Stage 1: Exact match
        if model_id in space_keys:
            self._match_cache[cache_key] = model_id
            return model_id

        # Stage 2: Scoped match
        scoped_id = f"{provider_id}/{model_id}" if provider_id else ""
        if scoped_id and scoped_id in space_keys:
            self._match_cache[cache_key] = scoped_id
            return scoped_id

        # Stage 3: Base slug match
        m_base = model_id.split("/")[-1].split(":")[0].lower()
        for k in space_keys:
            if k.split("/")[-1].split(":")[0].lower() == m_base:
                self._match_cache[cache_key] = k
                return k

        # Stage 4: Fuzzy & Substring Token Match (for local HF/MLX/GGUF models)
        cleaned = re.sub(r"(?i)[-_](mlx|4bit|8bit|16bit|gguf|q\d_[k0-9_]+|fp\d+|instruct|it|v\d+[\d\.]*)", "", m_base)
        tokens = set(re.findall(r"[a-z0-9]+", cleaned))
        ignored_tokens = {
            "it", "mlx", "gguf", "quant", "4bit", "8bit", "16bit", "fp16", "fp32", "v1", "v2",
            "vision", "model", "chat", "instruct", "text", "api", "base", "free", "pro", "flash",
            "mini", "small", "large", "turbo", "latest", "preview", "non", "dummy", "unknown"
        }
        clean_tokens = tokens - ignored_tokens
        query_digits = {t for t in clean_tokens if t.isdigit()}

        if len(clean_tokens) >= 2:
            best_match = ""
            best_score = 0
            for k in space_keys:
                k_base = k.split("/")[-1].split(":")[0].lower()
                k_tokens = set(re.findall(r"[a-z0-9]+", k_base)) - ignored_tokens
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
                self._match_cache[cache_key] = best_match
                return best_match

        self._match_cache[cache_key] = ""
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
                    with open(prov_cache, "r", encoding="utf-8") as f:
                        cdata = json.load(f)
                        lims = cdata.get("model_limits", {})
                        if lims:
                            res_prov = self._resolve_catalog_key(provider_id, model_id, lims, tag=f"prov_{provider_id}_limits")
                            if res_prov and res_prov in lims:
                                return lims[res_prov]
                except Exception:
                    pass

        return DEFAULT_CONTEXT_LIMIT

    def get_output_limit(self, provider_id: str, model_id: str) -> int:
        if not self._output_limits and not self._limits:
            self.load_cache()

        resolved = self._resolve_catalog_key(provider_id, model_id, self._output_limits, tag="output_limits")
        if resolved and resolved in self._output_limits:
            return self._output_limits[resolved]

        return 4096

    def supports_vision(self, provider_id: str, model_id: str) -> bool:
        if not model_id:
            return False
        if not self._vision and not self._limits:
            self.load_cache()

        resolved = self._resolve_catalog_key(provider_id, model_id, self._vision, tag="vision")
        if resolved and resolved in self._vision:
            return True

        return False

    def is_native_vision(self, provider_id: str, model_id: str) -> bool:
        if not model_id:
            return False
        if not self._vision and not self._limits:
            self.load_cache()

        native_list = [m for m in self._vision if m not in self._user_overrides]
        resolved = self._resolve_catalog_key(provider_id, model_id, native_list, tag="native_vision")
        if resolved and resolved in native_list:
            return True

        return False

    def supports_reasoning(self, provider_id: str, model_id: str) -> bool:
        if not model_id:
            return False
        if not self._reasoning and not self._limits:
            self.load_cache()

        resolved = self._resolve_catalog_key(provider_id, model_id, self._reasoning, tag="reasoning")
        if resolved and resolved in self._reasoning:
            return True

        return False

    def is_open_weights(self, provider_id: str, model_id: str) -> bool:
        if not model_id:
            return False
        if not self._open_weights and not self._limits:
            self.load_cache()

        resolved = self._resolve_catalog_key(provider_id, model_id, self._open_weights, tag="open_weights")
        if resolved and resolved in self._open_weights:
            return True

        return False

    def add_vision_override(self, model_id: str) -> None:
        if not model_id:
            return
        if not self._vision and not self._limits:
            self.load_cache()
        m_low = model_id.lower()
        if m_low not in [m.lower() for m in self._user_overrides]:
            self._user_overrides.append(model_id)
        if m_low not in [m.lower() for m in self._vision]:
            self._vision.append(model_id)
        self._match_cache.clear()
        self.save_cache()

    def remove_vision_override(self, model_id: str) -> None:
        if not model_id:
            return
        if not self._vision and not self._limits:
            self.load_cache()
        m_low = model_id.lower()
        self._user_overrides = [m for m in self._user_overrides if m.lower() != m_low]
        native_models = getattr(self, "_native_vision", None)
        if native_models is None:
            native_models = [m for m in self._vision if m.lower() != m_low]
        self._vision = list(set(native_models + self._user_overrides))
        self._match_cache.clear()
        self.save_cache()

    def set_fallback_vision_model(self, provider_id: str, model_id: str, explicit: bool = False) -> None:
        self._fallback_vision_provider = provider_id
        self._fallback_vision_model = model_id
        self._fallback_vision_explicit = explicit
        if model_id and not self.supports_vision(provider_id, model_id):
            self.add_vision_override(model_id)
        self.save_cache()
        self._save_vision_config(provider_id, model_id, explicit)

    def _save_vision_config(self, provider_id: str, model_id: str, explicit: bool = False) -> None:
        try:
            data = {}
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            if not isinstance(data, dict):
                data = {}
            data["fallback_vision_provider"] = provider_id
            data["fallback_vision_model"] = model_id
            data["fallback_vision_explicit"] = explicit
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def is_fallback_vision_explicit(self) -> bool:
        return getattr(self, "_fallback_vision_explicit", False)

    def get_fallback_vision_model(self) -> Tuple[str, str]:
        return getattr(self, "_fallback_vision_provider", ""), getattr(self, "_fallback_vision_model", "")

    def get_model_display_name(self, provider_id: str, model_id: str) -> str:
        if not model_id:
            return ""

        resolved = self._resolve_catalog_key(provider_id, model_id, self._names, tag="names")
        if resolved and resolved in self._names:
            return self._names[resolved]

        base_raw = model_id.split("/")[-1].split(":")[0]
        parts = base_raw.replace("_", "-").split("-")
        return " ".join(p.capitalize() if not p.isdigit() and len(p) > 1 else p for p in parts)

    def get_model_description(self, provider_id: str, model_id: str) -> str:
        if not model_id:
            return ""

        resolved = self._resolve_catalog_key(provider_id, model_id, self._descriptions, tag="descriptions")
        if resolved and resolved in self._descriptions:
            return self._descriptions[resolved]

        return ""

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
