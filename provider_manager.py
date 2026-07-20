import os
import json
import importlib.util
import shutil
from typing import Dict, Any, Type

CONFIG_DIR = os.path.expanduser("~/.tui")
PROVIDERS_DIR = os.path.join(CONFIG_DIR, "providers")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_OPENCODE_CONTENT = '''"""
OpenCode Go Provider configuration
"""
import time
from typing import AsyncGenerator, Tuple
from openai import AsyncOpenAI

NAME = "OpenCode Go (DeepSeek v4 Flash)"
KEY = "opencode"
DESCRIPTION = "Настоящий агент OpenCode Go (DeepSeek v4 Flash)"

BASE_URL = "https://opencode.ai/zen/go/v1"
MODEL = "deepseek-v4-flash"
API_KEY = "sk-placeholder"

SYSTEM_PROMPT = "Ты умный ИИ-ассистент, работающий через OpenCode Go с моделью DeepSeek v4 Flash. Отвечай точечно и качественно. Поддерживай Markdown."

class Agent:
    def __init__(self, api_key: str = API_KEY, model: str = MODEL, base_url: str = BASE_URL):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        self.history = []

    def clear_history(self):
        self.history.clear()

    async def stream_steps(self, user_text: str) -> AsyncGenerator[Tuple[str, str, str], None]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.history + [{"role": "user", "content": user_text}]

        t0 = time.time()
        thinking_text = ""
        is_thinking = False
        full_response = ""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True
            )

            async for chunk in response:
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                
                reasoning_delta = getattr(delta, "reasoning_content", None)
                if reasoning_delta:
                    if not is_thinking:
                        is_thinking = True
                        yield ("thinking_start", "Размышление над ответом...", "")
                    thinking_text += reasoning_delta
                
                if delta.content:
                    if is_thinking:
                        dt = time.time() - t0
                        yield ("thinking_end", f"{dt:.1f}", thinking_text)
                        is_thinking = False

                    full_response += delta.content
                    yield ("bot_chunk", delta.content, "")

            if is_thinking:
                dt = time.time() - t0
                yield ("thinking_end", f"{dt:.1f}", thinking_text)

            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": full_response})

        except Exception as err:
            if is_thinking:
                dt = time.time() - t0
                yield ("thinking_end", f"{dt:.1f}", f"Ошибка во время размышления: {err}")
            
            error_msg = f"❌ **Ошибка OpenCode API:** `{err}`"
            yield ("bot_text", error_msg, "")
'''

DEFAULT_MOCK_CONTENT = '''"""
Mock Agent Provider
"""
import asyncio
from typing import AsyncGenerator, Tuple

NAME = "Mock Agent (Симулятор)"
KEY = "mock"
DESCRIPTION = "Локальный симулятор работы агента"

class Agent:
    def __init__(self):
        self.history = []

    def clear_history(self):
        self.history.clear()

    async def stream_steps(self, user_text: str) -> AsyncGenerator[Tuple[str, str, str], None]:
        yield ("thinking_start", f"**Анализ запроса:** «{user_text.strip()}»", "")
        await asyncio.sleep(0.5)
        yield ("thinking_end", "0.5", "Запрос обработан локальным Mock-агентом.")
        await asyncio.sleep(0.2)
        yield ("tool", "Read", "/Users/yegor/tui/app.py")
        await asyncio.sleep(0.2)
        yield ("bot_text", f"Это симулированный ответ Mock-агента на: **{user_text}**", "")
'''

class ProviderManager:
    def __init__(self):
        self.ensure_config_dir()

    def ensure_config_dir(self):
        os.makedirs(PROVIDERS_DIR, exist_ok=True)
        
        # Создаем дефолтные конфиги провайдеров если пустая папка
        opencode_file = os.path.join(PROVIDERS_DIR, "opencode.py")
        if not os.path.exists(opencode_file):
            with open(opencode_file, "w", encoding="utf-8") as f:
                f.write(DEFAULT_OPENCODE_CONTENT.strip())

        mock_file = os.path.join(PROVIDERS_DIR, "mock.py")
        if not os.path.exists(mock_file):
            with open(mock_file, "w", encoding="utf-8") as f:
                f.write(DEFAULT_MOCK_CONTENT.strip())

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
                    print(f"Ошибка загрузки провайдера {filename}: {e}")

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
            raise RuntimeError("Нет доступных провайдеров в ~/.tui/providers/")
