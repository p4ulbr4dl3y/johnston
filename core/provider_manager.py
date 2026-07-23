import importlib.util
import json
import os
import sys
import time
from typing import Any, Dict, List

import httpx

from core.config import CONFIG_DIR, CONFIG_FILE, PROVIDERS_DIR

johnston_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
core_dir = os.path.dirname(os.path.abspath(__file__))
if johnston_dir not in sys.path:
    sys.path.insert(0, johnston_dir)
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)



def _get_default_opencode_template() -> str:
    template_path = os.path.join(johnston_dir, "templates", "opencode_provider.py.template")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

class ProviderManager:
    def __init__(self):
        self.ensure_config_dir()

    def ensure_config_dir(self):
        os.makedirs(PROVIDERS_DIR, exist_ok=True)
        os.makedirs(CONFIG_DIR, exist_ok=True)

        opencode_file = os.path.join(PROVIDERS_DIR, "opencode.py")
        if not os.path.exists(opencode_file):
            content = _get_default_opencode_template()
            if content:
                with open(opencode_file, "w", encoding="utf-8") as f:
                    f.write(content.strip())

        if not os.path.exists(CONFIG_FILE):
            self.set_active_provider_key("opencode")

    def load_providers(self) -> Dict[str, Any]:
        """Dynamically loads all .py providers from local providers/ directory"""
        providers = {}
        if not os.path.exists(PROVIDERS_DIR):
            return providers

        for filename in os.listdir(PROVIDERS_DIR):
            if filename.endswith(".py") and not filename.startswith("_"):
                filepath = os.path.join(PROVIDERS_DIR, filename)
                mod_name = f"johnston_provider_{filename[:-3]}"

                try:
                    spec = importlib.util.spec_from_file_location(mod_name, filepath)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)

                        provider_key = getattr(module, "KEY", filename[:-3])
                        provider_name = getattr(module, "NAME", provider_key)

                        if hasattr(module, "Agent"):
                            providers[provider_key] = {
                                "key": provider_key,
                                "name": provider_name,
                                "description": getattr(module, "DESCRIPTION", ""),
                                "module": module,
                                "file": filepath
                            }
                except Exception as e:
                    print(f"Error loading provider {filename}: {e}")

        return providers

    def get_active_provider_key(self) -> str:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("active_provider", "opencode")
            except Exception:
                pass
        return "opencode"

    def set_active_provider_key(self, key: str):
        data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["active_provider"] = key
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

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
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def set_provider_model(self, key: str, model_name: str):
        """Saves selected model for provider to config and provider .py file"""
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
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        provider_path = os.path.join(PROVIDERS_DIR, f"{key}.py")
        if os.path.exists(provider_path):
            try:
                with open(provider_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                new_lines = []
                for line in lines:
                    if line.startswith("MODEL ="):
                        new_lines.append(f'MODEL = "{model_name}"\n')
                    else:
                        new_lines.append(line)
                with open(provider_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
            except Exception as e:
                print(f"Error updating model in provider file {key}.py: {e}")

    def create_active_agent(self):
        providers = self.load_providers()
        active_key = self.get_active_provider_key()

        target_provider = None
        if active_key in providers:
            target_provider = providers[active_key]
        elif providers:
            first_key = list(providers.keys())[0]
            target_provider = providers[first_key]
        else:
            raise RuntimeError("No available providers in project providers/")

        mod = target_provider["module"]
        stored_key = self.get_api_key(active_key)
        kwargs = {}
        if stored_key:
            kwargs["api_key"] = stored_key

        agent = mod.Agent(**kwargs)

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    p_models = cdata.get("provider_models", {})
                    if active_key in p_models:
                        agent.model = p_models[active_key]
            except Exception:
                pass

        return agent

    async def fetch_models_for_provider(self, provider_key: str, force_refresh: bool = False) -> List[str]:
        """Returns cached list of provider models (TTL = 24h) or performs HTTP request"""
        CACHE_DIR = os.path.join(CONFIG_DIR, "cache")
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(CACHE_DIR, f"models_{provider_key}.json")

        # 1. Check cache file
        if not force_refresh and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    age = time.time() - cdata.get("updated_at", 0)
                    if age < 86400 and cdata.get("models"):
                        return cdata["models"]
            except Exception:
                pass

        # 2. Request models via provider HTTP API
        providers = self.load_providers()
        if provider_key not in providers:
            return []

        mod = providers[provider_key]["module"]
        base_url = getattr(mod, "BASE_URL", None)
        api_key = self.get_api_key(provider_key) or getattr(mod, "API_KEY", None)

        models = []
        model_limits = {}
        vision_models = []
        if base_url:
            models_url = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(models_url, headers=headers, timeout=10)
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

                                arch = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
                                input_mods = arch.get("input_modalities") or m.get("input_modalities") or m.get("modalities") or []
                                if "image" in input_mods or "vision" in input_mods:
                                    vision_models.append(m_id)
            except Exception as e:
                print(f"Error fetching models for {provider_key}: {e}")

        # Fallback to models list from module or default model
        if not models:
            if hasattr(mod, "MODELS") and isinstance(mod.MODELS, list):
                models = mod.MODELS
            elif hasattr(mod, "MODEL"):
                models = [mod.MODEL]

        # Save to cache
        if models:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"updated_at": time.time(), "models": models, "model_limits": model_limits, "vision_models": vision_models}, f, indent=2)
            except Exception as e:
                print(f"Error writing models cache: {e}")

        return models

    async def fetch_models_grouped(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """Returns model dictionaries grouped by provider"""
        providers = self.load_providers()
        grouped = {}
        for p_key, p_data in providers.items():
            models = await self.fetch_models_for_provider(p_key, force_refresh=force_refresh)
            grouped[p_key] = {
                "name": p_data["name"],
                "models": models
            }
        return grouped

