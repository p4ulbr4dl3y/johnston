import os
import json
import time
import importlib.util
import shutil
import sys
from typing import Dict, Any, Type
from config import CONFIG_DIR, PROVIDERS_DIR, CONFIG_FILE

# Add the directory containing provider_manager.py to sys.path so dynamic modules can import from it
tui_dir = os.path.dirname(os.path.abspath(__file__))
if tui_dir not in sys.path:
    sys.path.insert(0, tui_dir)

DEFAULT_OPENCODE_CONTENT = '''"""
OpenCode Go Provider configuration with Read, Create, Edit, Bash tools support
"""
from base_provider import BaseAgent

NAME = "OpenCode Go (DeepSeek v4 Flash)"
KEY = "opencode"
DESCRIPTION = "OpenCode Go agent (DeepSeek v4 Flash) with Read, Create, Edit, and Bash tools"

BASE_URL = "https://opencode.ai/zen/go/v1"
MODEL = "deepseek-v4-flash"
API_KEY = "sk-placeholder"

SYSTEM_PROMPT = """You write code.
Tools: Read, Create, Edit, Bash, Glob, Grep, AskUser.
Rules:
- Read: Read file path.
- Create: Write new file.
- Edit: Replace unique block of text (old_string) with new_string in existing file. Must match indentation.
- Bash: Run command. Runs in background if >5s.
- Glob: Search file paths by pattern.
- Grep: Search text inside files by regex.
- AskUser: Ask question to user."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read file content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Create",
            "description": "Create new file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path"},
                    "content": {"type": "string", "description": "File content"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "Replace text block (old_string) with new_string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path"},
                    "old_string": {"type": "string", "description": "Exact text to replace"},
                    "new_string": {"type": "string", "description": "Replacement text"}
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Run terminal command. >5s runs in background.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Search file paths by pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. **/*.py)"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search text inside files by regex.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "AskUser",
            "description": "Ask question to user. Can ask single text question, or a list of questions with pre-defined options and write-ins.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Single text question to ask."},
                    "questions": {
                        "type": "array",
                        "description": "List of questions to ask sequentially in a wizard.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "num_text": {"type": "string", "description": "Header text (e.g. 'Question 1/2')"},
                                "question_text": {"type": "string", "description": "The actual question text"},
                                "options": {
                                    "type": "array",
                                    "description": "List of pre-defined options",
                                    "items": {"type": "string"}
                                }
                            },
                            "required": ["question_text"]
                        }
                    }
                }
            }
        }
    }
]

class Agent(BaseAgent):
    def __init__(self, api_key: str = API_KEY, model: str = MODEL, base_url: str = BASE_URL):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            system_prompt=SYSTEM_PROMPT,
            tools=TOOLS
        )
'''

class ProviderManager:
    def __init__(self):
        self.ensure_config_dir()

    def ensure_config_dir(self):
        os.makedirs(PROVIDERS_DIR, exist_ok=True)
        
        opencode_file = os.path.join(PROVIDERS_DIR, "opencode.py")
        if not os.path.exists(opencode_file):
            with open(opencode_file, "w", encoding="utf-8") as f:
                f.write(DEFAULT_OPENCODE_CONTENT.strip())

        if not os.path.exists(CONFIG_FILE):
            self.set_active_provider_key("opencode")

    def load_providers(self) -> Dict[str, Any]:
        """Динамически загружает все .py провайдеры из ~/.tui/providers/"""
        providers = {}
        if not os.path.exists(PROVIDERS_DIR):
            return providers

        for filename in os.listdir(PROVIDERS_DIR):
            if filename.endswith(".py") and not filename.startswith("_"):
                filepath = os.path.join(PROVIDERS_DIR, filename)
                mod_name = f"tui_provider_{filename[:-3]}"
                
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
        data = {"active_provider": key}
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def create_active_agent(self):
        providers = self.load_providers()
        active_key = self.get_active_provider_key()
        
        if active_key in providers:
            return providers[active_key]["module"].Agent()
        elif providers:
            first_key = list(providers.keys())[0]
            return providers[first_key]["module"].Agent()
        else:
            raise RuntimeError("No available providers in ~/.tui/providers/")

    async def fetch_models_for_provider(self, provider_key: str, force_refresh: bool = False) -> list[str]:
        """Возвращает кешированный список моделей провайдера (TTL = 24 часа) или делает HTTP запрос"""
        CACHE_DIR = os.path.join(CONFIG_DIR, "cache")
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(CACHE_DIR, f"models_{provider_key}.json")

        # 1. Проверяем файл кеша
        if not force_refresh and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    age = time.time() - cdata.get("updated_at", 0)
                    if age < 86400 and cdata.get("models"):
                        return cdata["models"]
            except Exception:
                pass

        # 2. Запрашиваем модели через HTTP API провайдера
        providers = self.load_providers()
        if provider_key not in providers:
            return []

        mod = providers[provider_key]["module"]
        base_url = getattr(mod, "BASE_URL", None)
        api_key = getattr(mod, "API_KEY", None)

        models = []
        if base_url:
            import httpx
            models_url = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(models_url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
            except Exception as e:
                print(f"Error fetching models for {provider_key}: {e}")

        # Фолбэк на дефолтную модель
        if not models and hasattr(mod, "MODEL"):
            models = [mod.MODEL]

        # Записываем в кеш
        if models:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"updated_at": time.time(), "models": models}, f, indent=2)
            except Exception as e:
                print(f"Error writing models cache: {e}")

        return models
