"""
AI Model Catalog and Context Limit Manager for Johnston.
Fetches model context limits dynamically from provider APIs, OpenRouter catalog API, or defaults.
"""
import json
import os
import time
from typing import Dict, List

import httpx

from core.config import CONFIG_DIR

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_FILE = os.path.join(CONFIG_DIR, "cache", "openrouter_catalog.json")
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
        self._vision: List[str] = []
        self._names: Dict[str, str] = {}
        self._pricing: Dict[str, Dict[str, float]] = {}
        self.load_cache()

    def load_cache(self) -> bool:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if time.time() - data.get("updated_at", 0) < CACHE_TTL:
                        self._limits = data.get("model_limits", {})
                        self._vision = data.get("vision_models", [])
                        self._names = data.get("model_names", {})
                        self._pricing = data.get("model_pricing", {})
                        return True
            except Exception:
                pass
        return False

    def save_cache(
        self,
        model_limits: Dict[str, int],
        vision_models: List[str],
        model_names: Dict[str, str],
        model_pricing: Dict[str, Dict[str, float]] = None,
    ):
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "updated_at": time.time(),
                        "model_limits": model_limits,
                        "vision_models": vision_models,
                        "model_names": model_names,
                        "model_pricing": model_pricing or {},
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            print(f"Error saving openrouter catalog cache: {e}")

    async def refresh(self) -> Dict[str, int]:
        model_limits: Dict[str, int] = {}
        vision_models: List[str] = []
        model_names: Dict[str, str] = {}
        model_pricing: Dict[str, Dict[str, float]] = {}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(OPENROUTER_MODELS_URL, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", []):
                        if isinstance(m, dict) and "id" in m:
                            m_id = m["id"]
                            raw_name = m.get("name", "")
                            clean_name = raw_name.split(": ", 1)[-1] if ": " in raw_name else raw_name
                            if clean_name:
                                model_names[m_id] = clean_name
                                model_names[m_id.split("/")[-1].lower()] = clean_name

                            ctx = (
                                m.get("context_length")
                                or (m.get("top_provider", {}) or {}).get("context_length")
                                or m.get("context_window")
                            )
                            if ctx and isinstance(ctx, (int, float)):
                                model_limits[m_id] = int(ctx)

                            arch = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
                            input_mods = (
                                arch.get("input_modalities")
                                or m.get("input_modalities")
                                or m.get("modalities")
                                or []
                            )
                            if "image" in input_mods or "vision" in input_mods:
                                vision_models.append(m_id)

                            pricing_raw = m.get("pricing") if isinstance(m.get("pricing"), dict) else {}
                            p_prompt = float(pricing_raw.get("prompt") or 0.0)
                            p_comp = float(pricing_raw.get("completion") or 0.0)
                            if p_prompt > 0 or p_comp > 0:
                                p_item = {"prompt": p_prompt, "completion": p_comp}
                                model_pricing[m_id] = p_item
                                model_pricing[m_id.split("/")[-1].lower()] = p_item

                    self._limits = model_limits
                    self._vision = vision_models
                    self._names = model_names
                    self._pricing = model_pricing
                    self.save_cache(model_limits, vision_models, model_names, model_pricing)
        except Exception as e:
            print(f"Error fetching OpenRouter models catalog: {e}")
        return self._limits

    def get_context_limit(self, provider_id: str, model_id: str) -> int:
        cache_dir = os.path.join(CONFIG_DIR, "cache")

        # 1. Check local provider cache
        cache_path = os.path.join(cache_dir, f"models_{provider_id}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    limits = cdata.get("model_limits", {})
                    if model_id in limits and isinstance(limits[model_id], (int, float)):
                        return int(limits[model_id])
            except Exception:
                pass

        # 2. Check OpenRouter catalog cache
        if not self._limits:
            self.load_cache()

        if model_id in self._limits:
            return self._limits[model_id]

        m_base = model_id.split("/")[-1].lower()
        for k, v in self._limits.items():
            if k.split("/")[-1].lower() == m_base and isinstance(v, (int, float)):
                return int(v)

        return DEFAULT_CONTEXT_LIMIT

    def supports_vision(self, provider_id: str, model_id: str) -> bool:
        cache_path = os.path.join(CONFIG_DIR, "cache", f"models_{provider_id}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    vision_models = cdata.get("vision_models")
                    if isinstance(vision_models, list) and vision_models:
                        return model_id in vision_models
            except Exception:
                pass

        if not self._vision:
            self.load_cache()

        if model_id in self._vision:
            return True

        m_base = model_id.split("/")[-1].lower()
        for k in self._vision:
            if k.split("/")[-1].lower() == m_base:
                return True

        return False

    def get_model_display_name(self, provider_id: str, model_id: str) -> str:
        if not model_id:
            return ""

        if not self._names:
            self.load_cache()

        if model_id in self._names:
            return self._names[model_id]

        m_base = model_id.split("/")[-1].lower()
        if m_base in self._names:
            return self._names[m_base]

        # Fallback clean formatting without organization prefix
        base_raw = model_id.split("/")[-1]
        parts = base_raw.replace("_", "-").split("-")
        capitalized = " ".join(p.capitalize() if not p.isdigit() and len(p) > 1 else p for p in parts)
        return capitalized

    def get_model_pricing(self, provider_id: str, model_id: str) -> Dict[str, float]:
        cache_path = os.path.join(CONFIG_DIR, "cache", f"models_{provider_id}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    pricing = cdata.get("model_pricing", {})
                    if model_id in pricing and isinstance(pricing[model_id], dict):
                        return pricing[model_id]
            except Exception:
                pass

        if not self._pricing:
            self.load_cache()

        if model_id in self._pricing:
            return self._pricing[model_id]

        m_base = model_id.split("/")[-1].lower()
        if m_base in self._pricing:
            return self._pricing[m_base]

        return {"prompt": 0.0, "completion": 0.0}


catalog = ModelsCatalog()


def get_context_window(provider_id: str, model_id: str) -> str:
    limit = catalog.get_context_limit(provider_id, model_id)
    return format_context_tokens(limit)
