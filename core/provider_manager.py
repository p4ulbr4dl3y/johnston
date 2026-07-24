import importlib.util
import json
import os
import sys
import time
from typing import Any, Dict, List

import httpx

from core.config import CONFIG_DIR, CONFIG_FILE, PROVIDERS_DIR, PROVIDERS_JSON_FILE

johnston_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
core_dir = os.path.dirname(os.path.abspath(__file__))
if johnston_dir not in sys.path:
    sys.path.insert(0, johnston_dir)
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)


DEFAULT_JSON_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "opencode": {
        "key": "opencode",
        "name": "OpenCode",
        "description": "OpenCode agent provider",
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "deepseek-v4-flash",
        "api_type": "openai",
    },
    "clinepass": {
        "key": "clinepass",
        "name": "ClinePass",
        "description": "ClinePass AI provider",
        "base_url": "https://api.cline.bot/api/v1",
        "api_type": "openai",
        "models": [
            "cline-pass/glm-5.2",
            "cline-pass/kimi-k3",
            "cline-pass/kimi-k2.7-code",
            "cline-pass/kimi-k2.6",
            "cline-pass/deepseek-v4-pro",
            "cline-pass/deepseek-v4-flash",
            "cline-pass/mimo-v2.5",
            "cline-pass/mimo-v2.5-pro",
            "cline-pass/minimax-m3",
            "cline-pass/qwen3.7-max",
            "cline-pass/qwen3.7-plus",
        ],
    },
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
    "ollama": {
        "key": "ollama",
        "name": "Ollama",
        "description": "Local Ollama server",
        "base_url": "http://localhost:11434/v1",
        "api_type": "ollama",
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
        self.ensure_config_dir()

    def ensure_config_dir(self):
        os.makedirs(PROVIDERS_DIR, exist_ok=True)
        os.makedirs(CONFIG_DIR, exist_ok=True)

        if not os.path.exists(PROVIDERS_JSON_FILE):
            try:
                with open(PROVIDERS_JSON_FILE, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_JSON_PROVIDERS, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        if not os.path.exists(CONFIG_FILE):
            self.set_active_provider_key("opencode")

    def _load_json_providers(self) -> Dict[str, Dict[str, Any]]:
        providers = dict(DEFAULT_JSON_PROVIDERS)
        if os.path.exists(PROVIDERS_JSON_FILE):
            try:
                with open(PROVIDERS_JSON_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, dict):
                                providers[k] = v
            except Exception:
                pass
        return providers

    def load_providers(self) -> Dict[str, Any]:
        """Loads providers from JSON definitions + Python plugin files in providers/"""
        providers = {}

        # 1. Load JSON providers
        json_providers = self._load_json_providers()
        for pkey, pdata in json_providers.items():
            providers[pkey] = {
                "key": pkey,
                "name": pdata.get("name", pkey),
                "description": pdata.get("description", ""),
                "base_url": pdata.get("base_url", ""),
                "model": pdata.get("model", ""),
                "models": pdata.get("models", []),
                "fetch_models": pdata.get("fetch_models", True),
                "api_type": pdata.get("api_type", "openai"),
                "source": "json",
            }

        # 2. Load .py plugins from PROVIDERS_DIR (take precedence if defined)
        if os.path.exists(PROVIDERS_DIR):
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
                                    "base_url": getattr(module, "BASE_URL", ""),
                                    "model": getattr(module, "MODEL", ""),
                                    "module": module,
                                    "file": filepath,
                                    "source": "python",
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
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Also update JSON providers file if present
        if os.path.exists(PROVIDERS_JSON_FILE):
            try:
                with open(PROVIDERS_JSON_FILE, "r", encoding="utf-8") as f:
                    jdata = json.load(f)
                if key in jdata:
                    jdata[key]["model"] = model_name
                    with open(PROVIDERS_JSON_FILE, "w", encoding="utf-8") as f:
                        json.dump(jdata, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        # Update .py provider file if present
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
            raise RuntimeError("No available providers configured.")

        stored_key = self.get_api_key(target_provider["key"])
        kwargs = {}
        if stored_key:
            kwargs["api_key"] = stored_key

        if "module" in target_provider and hasattr(target_provider["module"], "Agent"):
            agent = target_provider["module"].Agent(**kwargs)
        else:
            from core.base_provider import BaseAgent
            agent = BaseAgent(
                api_key=stored_key or target_provider.get("api_key", ""),
                model=target_provider.get("model", "gpt-4o"),
                base_url=target_provider.get("base_url", ""),
                system_prompt=target_provider.get("system_prompt", "You write code and execute tasks."),
                provider_key=target_provider["key"],
                api_type=target_provider.get("api_type", "openai"),
            )

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

        pdata = providers[provider_key]
        mod = pdata.get("module")
        base_url = getattr(mod, "BASE_URL", None) if mod else pdata.get("base_url")
        api_key = self.get_api_key(provider_key) or (getattr(mod, "API_KEY", None) if mod else pdata.get("api_key"))

        models = []
        model_limits = {}
        vision_models = []
        should_fetch = pdata.get("fetch_models", True)
        if base_url and should_fetch:
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

        # Universal fallback to static models list, module, or default model for ANY provider
        if not models:
            if pdata.get("models"):
                models = list(pdata["models"])
            elif mod and hasattr(mod, "MODELS") and isinstance(mod.MODELS, list):
                models = list(mod.MODELS)
            elif mod and hasattr(mod, "MODEL"):
                models = [mod.MODEL]
            elif pdata.get("model"):
                models = [pdata["model"]]

        # Save to cache
        if models:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"updated_at": time.time(), "models": models, "model_limits": model_limits, "vision_models": vision_models}, f, indent=2)
            except Exception as e:
                print(f"Error writing models cache: {e}")

        return models

    async def fetch_models_grouped(self, force_refresh: bool = False, connected_only: bool = True) -> Dict[str, Dict[str, Any]]:
        """Returns model dictionaries grouped by provider (only connected/configured providers by default)"""
        providers = self.load_providers()
        grouped = {}
        for p_key, p_data in providers.items():
            models = await self.fetch_models_for_provider(p_key, force_refresh=force_refresh)
            if connected_only and not models:
                continue
            grouped[p_key] = {
                "name": p_data["name"],
                "models": models
            }
        return grouped
