import asyncio
import os
import time
import json
from typing import AsyncGenerator, Tuple, Dict, Any
from openai import AsyncOpenAI

PERSONAS = {
    "opencode": {
        "name": "⚡ OpenCode (DeepSeek v4 Flash)",
        "description": "Настоящий агент OpenCode Go (DeepSeek v4 Flash) с инструментами Read, Create, Edit, Bash",
        "system": "Ты инженер-разработчик. Тебе доступны инструменты Read, Create, Edit, Bash. Создавай и редактируй файлы в текущем проекте."
    }
}

OPENCODE_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_API_KEY = "sk-placeholder"

MODEL_INFO = {
    "deepseek-v4-flash": {"context": "128k", "prompt_cost": 0.15, "completion_cost": 0.60},
    "deepseek-v4-pro": {"context": "128k", "prompt_cost": 0.27, "completion_cost": 1.10},
    "qwen3.7-max": {"context": "128k", "prompt_cost": 0.40, "completion_cost": 1.20},
    "glm-5": {"context": "128k", "prompt_cost": 0.50, "completion_cost": 1.00},
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Прочитать файл из текущего проекта",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Относительный или абсолютный путь к файлу"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Create",
            "description": "Создать новый файл в текущем проекте",
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
            "description": "Изменить или перезаписать файл в текущем проекте",
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
            "description": "Выполнить bash команду в текущем проекте",
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

def resolve_project_path(raw_path: str) -> str:
    """Приводит путь к текущей рабочей директории проекта, предотвращая запись в / (root)"""
    path = os.path.expanduser(raw_path)
    cwd = os.path.realpath(os.getcwd())
    
    if not os.path.isabs(path):
        return os.path.normpath(os.path.join(cwd, path))
    
    if path.startswith('/') and not path.startswith(cwd) and not path.startswith('/Users') and not path.startswith('/tmp') and not path.startswith('/private'):
        return os.path.normpath(os.path.join(cwd, path.lstrip('/')))
        
    return os.path.normpath(path)

async def execute_tool(name: str, args: dict) -> str:
    """Локальное выполнение инструментов Read, Create, Edit, Bash"""
    try:
        if name == "Read":
            raw_path = args.get("path", "")
            path = resolve_project_path(raw_path)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if len(content) > 4000:
                        content = content[:4000] + "\n... [содержимое обрезано]"
                    return content
            return f"Ошибка: файл '{path}' не найден."

        elif name in ("Create", "Edit"):
            raw_path = args.get("path", "")
            path = resolve_project_path(raw_path)
            content = args.get("content", "")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            rel_path = os.path.relpath(path, os.getcwd())
            return f"Успешно: файл '{rel_path}' сохранен ({len(content)} байт)."

        elif name == "Bash":
            cmd = args.get("command", "")
            p = await asyncio.create_subprocess_shell(
                cmd,
                cwd=os.getcwd(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await p.communicate()
            res = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
            if len(res) > 3000:
                res = res[:3000] + "\n... [вывод обрезан]"
            return res if res.strip() else "Команда выполнена без вывода."

    except Exception as err:
        return f"Ошибка выполнения инструмента {name}: {err}"
    
    return "Неизвестный инструмент."


class OpenCodeAgent:
    def __init__(self, api_key: str = DEFAULT_API_KEY, model: str = DEFAULT_MODEL, persona_key: str = "opencode"):
        self.api_key = api_key
        self.model = model
        self.persona_key = persona_key
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=OPENCODE_BASE_URL)
        self.history = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost = 0.0

    def set_persona(self, persona_key: str):
        if persona_key in PERSONAS:
            self.persona_key = persona_key

    def clear_history(self):
        self.history.clear()
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost = 0.0

    def get_metrics(self) -> dict:
        info = MODEL_INFO.get(self.model, {"context": "128k"})
        return {
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "cost_usd": self.total_cost,
            "context": info.get("context", "128k")
        }

    async def stream_steps(self, user_text: str) -> AsyncGenerator[Tuple[str, str, str], None]:
        """
        Генерирует поток сообщений для TUI ChatView с поддержкой инструментов Read, Create, Edit, Bash.
        """
        cwd = os.path.realpath(os.getcwd())
        system_prompt = (
            PERSONAS.get(self.persona_key, PERSONAS["opencode"])["system"] +
            f"\nТекущая рабочая директория проекта: {cwd}. Все файлы создавай относительно этой директории."
        )
        messages = [{"role": "system", "content": system_prompt}] + self.history + [{"role": "user", "content": user_text}]

        t0 = time.time()
        full_assistant_text = ""

        try:
            while True:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    stream=True,
                    stream_options={"include_usage": True}
                )

                thinking_text = ""
                is_thinking = False
                current_text = ""
                tool_calls_dict = {}

                async for chunk in response:
                    if getattr(chunk, "usage", None) and chunk.usage:
                        p_tok = chunk.usage.prompt_tokens or 0
                        c_tok = chunk.usage.completion_tokens or 0
                        self.total_prompt_tokens += p_tok
                        self.total_completion_tokens += c_tok
                        
                        info = MODEL_INFO.get(self.model, {"prompt_cost": 0.20, "completion_cost": 0.80})
                        cost = (p_tok * info.get("prompt_cost", 0.20) + c_tok * info.get("completion_cost", 0.80)) / 1_000_000
                        self.total_cost += cost

                    if not chunk.choices:
                        continue
                    
                    delta = chunk.choices[0].delta

                    # 1. Reasoning
                    reasoning_delta = getattr(delta, "reasoning_content", None)
                    if reasoning_delta:
                        if not is_thinking:
                            is_thinking = True
                            yield ("thinking_start", "Размышление над ответами...", "")
                        thinking_text += reasoning_delta

                    # 2. Text Content
                    if delta.content:
                        if is_thinking:
                            dt = time.time() - t0
                            yield ("thinking_end", f"{dt:.1f}", thinking_text)
                            is_thinking = False

                        current_text += delta.content
                        full_assistant_text += delta.content
                        yield ("bot_chunk", delta.content, "")

                    # 3. Tool Calls Delta
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

                    raw_target = args.get("path") or args.get("command") or t_name
                    target = raw_target
                    if args.get("path"):
                        target = os.path.relpath(resolve_project_path(args["path"]), os.getcwd())

                    yield ("tool", t_name, target)

                    tool_result = await execute_tool(t_name, args)
                    yield ("tool_result", tool_result, "")

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
