import os
import json
import time
import importlib.util
import shutil
from typing import Dict, Any, Type

CONFIG_DIR = os.path.expanduser("~/.tui")
PROVIDERS_DIR = os.path.join(CONFIG_DIR, "providers")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_OPENCODE_CONTENT = '''"""
OpenCode Go Provider configuration with Read, Create, Edit, Bash tools support
"""
import asyncio
import os
import time
import json
from typing import AsyncGenerator, Tuple
from openai import AsyncOpenAI

NAME = "OpenCode Go (DeepSeek v4 Flash)"
KEY = "opencode"
DESCRIPTION = "Настоящий агент OpenCode Go (DeepSeek v4 Flash) с поддержкой инструментов Read, Create, Edit, Bash"

BASE_URL = "https://opencode.ai/zen/go/v1"
MODEL = "deepseek-v4-flash"
API_KEY = "sk-placeholder"

SYSTEM_PROMPT = "Ты инженер-разработчик. Тебе доступны инструменты Read, Create, Edit, Bash. Используй их для просмотра, создания и изменения файлов, а также выполнения терминальных команд."

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Прочитать файл из файловой системы",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Create",
            "description": "Создать новый файл",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу"},
                    "content": {"type": "string", "description": "Содержимое файла"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "Изменить или перезаписать файл",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу"},
                    "content": {"type": "string", "description": "Новое содержимое файла"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Выполнить bash команду в терминале",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Команда bash"}
                },
                "required": ["command"]
            }
        }
    }
]

async def execute_tool(name: str, args: dict) -> str:
    """Локальное выполнение инструментов Read, Create, Edit, Bash"""
    try:
        if name == "Read":
            path = os.path.expanduser(args.get("path", ""))
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if len(content) > 4000:
                        content = content[:4000] + "\\n... [содержимое обрезано]"
                    return content
            return f"Ошибка: файл '{path}' не найден."

        elif name in ("Create", "Edit"):
            path = os.path.expanduser(args.get("path", ""))
            content = args.get("content", "")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Успешно: файл '{path}' сохранен ({len(content)} байт)."

        elif name == "Bash":
            cmd = args.get("command", "")
            p = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await p.communicate()
            res = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
            if len(res) > 3000:
                res = res[:3000] + "\\n... [вывод обрезан]"
            return res if res.strip() else "Команда выполнена без вывода."

    except Exception as err:
        return f"Ошибка выполнения инструмента {name}: {err}"
    
    return "Неизвестный инструмент."


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
        full_assistant_text = ""

        try:
            while True:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    stream=True
                )

                thinking_text = ""
                is_thinking = False
                current_text = ""
                tool_calls_dict = {}

                async for chunk in response:
                    if not chunk.choices:
                        continue
                    
                    delta = chunk.choices[0].delta

                    reasoning_delta = getattr(delta, "reasoning_content", None)
                    if reasoning_delta:
                        if not is_thinking:
                            is_thinking = True
                            yield ("thinking_start", "Размышление над ответами...", "")
                        thinking_text += reasoning_delta

                    if delta.content:
                        if is_thinking:
                            dt = time.time() - t0
                            yield ("thinking_end", f"{dt:.1f}", thinking_text)
                            is_thinking = False

                        current_text += delta.content
                        full_assistant_text += delta.content
                        yield ("bot_chunk", delta.content, "")

                    if delta.tool_calls:
                        if is_thinking:
                            dt = time.time() - t0
                            yield ("thinking_end", f"{dt:.1f}", thinking_text)
                            is_thinking = False

                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {
                                    "id": tc.id or f"call_{idx}",
                                    "name": tc.function.name or "",
                                    "arguments": tc.function.arguments or ""
                                }
                            else:
                                if tc.function.name:
                                    tool_calls_dict[idx]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls_dict[idx]["arguments"] += tc.function.arguments

                if is_thinking:
                    dt = time.time() - t0
                    yield ("thinking_end", f"{dt:.1f}", thinking_text)

                if not tool_calls_dict:
                    break

                assistant_tool_msg = {
                    "role": "assistant",
                    "content": current_text or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"]
                            }
                        }
                        for tc in tool_calls_dict.values()
                    ]
                }
                messages.append(assistant_tool_msg)

                for tc in tool_calls_dict.values():
                    t_id = tc["id"]
                    t_name = tc["name"]
                    raw_args = tc["arguments"]
                    
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}

                    target = args.get("path") or args.get("command") or t_name
                    yield ("tool", t_name, target)

                    tool_result = await execute_tool(t_name, args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": t_id,
                        "content": tool_result
                    })

            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": full_assistant_text})

        except Exception as err:
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
                print(f"Ошибка получения моделей {provider_key}: {e}")

        # Фолбэк на дефолтную модель
        if not models and hasattr(mod, "MODEL"):
            models = [mod.MODEL]

        # Записываем в кеш
        if models:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"updated_at": time.time(), "models": models}, f, indent=2)
            except Exception as e:
                print(f"Ошибка записи кеша моделей: {e}")

        return models
