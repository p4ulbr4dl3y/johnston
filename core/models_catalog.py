"""
AI Model Catalog and Context Limit Manager for Johnston.
Fetches model context limits dynamically from provider APIs, models.dev fallback, or defaults.
"""
import json
import os
import time
from typing import Any, Dict, Optional

import httpx

from core.config import CONFIG_DIR

MODELS_DEV_URL = "https://models.dev/api.json"
CACHE_FILE = os.path.join(CONFIG_DIR, "cache", "models_dev.json")
CACHE_TTL = 86400  # 24 hours

DEFAULT_CONTEXT_LIMIT = 128000


def format_context_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        val = tokens / 1_000_000
        if round(val, 1) == 1.0 or val % 1 == 0:
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
        self._data: Optional[Dict[str, Any]] = None
        self.load_cache()

    def load_cache(self) -> Optional[Dict[str, Any]]:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if time.time() - data.get("updated_at", 0) < CACHE_TTL:
                        self._data = data.get("providers", {})
                        return self._data
            except Exception:
                pass
        return None

    def save_cache(self, providers: Dict[str, Any]):
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"updated_at": time.time(), "providers": providers}, f, indent=2)
        except Exception as e:
            print(f"Error saving models_dev cache: {e}")

    async def refresh(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(MODELS_DEV_URL, timeout=10)
                if resp.status_code == 200:
                    providers = resp.json()
                    self._data = providers
                    self.save_cache(providers)
                    return providers
        except Exception as e:
            print(f"Error fetching models.dev: {e}")
        return self._data or {}

    def get_context_limit(self, provider_id: str, model_id: str) -> int:
        cache_path = os.path.join(CONFIG_DIR, "cache", f"models_{provider_id}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    limits = cdata.get("model_limits", {})
                    if model_id in limits and isinstance(limits[model_id], (int, float)):
                        return int(limits[model_id])
            except Exception:
                pass

        data = self._data
        if data and isinstance(data, dict):
            prov = data.get(provider_id)
            if prov and isinstance(prov, dict):
                models = prov.get("models", {})
                if model_id in models:
                    m = models[model_id]
                    limit = m.get("limit", {}).get("context")
                    if isinstance(limit, (int, float)):
                        return int(limit)

            for p_info in data.values():
                if isinstance(p_info, dict):
                    models = p_info.get("models", {})
                    if model_id in models:
                        m = models[model_id]
                        limit = m.get("limit", {}).get("context")
                        if isinstance(limit, (int, float)):
                            return int(limit)

        return DEFAULT_CONTEXT_LIMIT

    def supports_vision(self, provider_id: str, model_id: str) -> bool:
        """Проверяет, поддерживает ли модель обработку изображений (Vision) через input_modalities API или кэш"""
        # 1. Проверяем кеш моделей провайдера (~/.johnston/cache/models_{provider_id}.json)
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

        # 2. Проверяем данные из models.dev кеша по architecture.input_modalities
        data = self._data
        if data and isinstance(data, dict):
            for p_info in data.values():
                if isinstance(p_info, dict):
                    models = p_info.get("models", {})
                    if model_id in models:
                        m = models[model_id]
                        arch = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
                        modalities = arch.get("input_modalities") or m.get("input_modalities") or m.get("modalities") or []
                        if isinstance(modalities, list):
                            if "image" in modalities or "vision" in modalities:
                                return True
                            return False

        # 3. Эвристический запасной вариант по ключевым словам семейства модели
        m_lower = model_id.lower()
        vision_keywords = {
            "gpt-4o", "gpt-4-vision", "claude-3", "gemini", "vision", "omni",
            "qwen", "glm", "kimi", "mimo", "minimax", "nemotron"
        }
        for kw in vision_keywords:
            if kw in m_lower:
                return True

        return False


catalog = ModelsCatalog()


def get_context_window(provider_id: str, model_id: str) -> str:
    limit = catalog.get_context_limit(provider_id, model_id)
    return format_context_tokens(limit)
