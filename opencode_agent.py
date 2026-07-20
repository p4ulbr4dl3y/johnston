import asyncio
import time
from typing import AsyncGenerator, Tuple
from openai import AsyncOpenAI

PERSONAS = {
    "opencode": {
        "name": "⚡ OpenCode (DeepSeek v4 Flash)",
        "description": "Настоящий агент OpenCode Go (DeepSeek v4 Flash)",
        "system": "Ты умный ИИ-ассистент, работающий через OpenCode Go с моделью DeepSeek v4 Flash. Отвечай точечно, качественно и профессионально. Поддерживай форматирование Markdown и блоков кода."
    },
    "coder": {
        "name": "💻 Code Guru (DeepSeek)",
        "description": "Эксперт по коду Python, Rust, TS и Textual",
        "system": "Ты эксперт по программированию. Пиши чистый, рабочий код с подробными пояснениями."
    },
    "caveman": {
        "name": "🦴 Пещерный Чел",
        "description": "Говорит кратко, без лишних слов",
        "system": "Отвечать очень кратко, как умный пещерный человек. Техническая суть остается, лишние слова убрать."
    }
}

OPENCODE_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_API_KEY = "sk-placeholder"

class OpenCodeAgent:
    def __init__(self, api_key: str = DEFAULT_API_KEY, model: str = DEFAULT_MODEL, persona_key: str = "opencode"):
        self.api_key = api_key
        self.model = model
        self.persona_key = persona_key
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=OPENCODE_BASE_URL)
        self.history = []

    def set_persona(self, persona_key: str):
        if persona_key in PERSONAS:
            self.persona_key = persona_key

    def clear_history(self):
        self.history.clear()

    async def stream_steps(self, user_text: str) -> AsyncGenerator[Tuple[str, str, str], None]:
        """
        Генерирует поток сообщений для TUI ChatView.
        Типы событий:
          - ("thinking_start", details, "")
          - ("thinking_end", duration_str, full_thinking_text)
          - ("tool", tool_name, target)
          - ("bot_chunk", delta_text, "")
          - ("bot_text", full_text, "")
        """
        system_prompt = PERSONAS.get(self.persona_key, PERSONAS["opencode"])["system"]
        
        messages = [{"role": "system", "content": system_prompt}] + self.history + [{"role": "user", "content": user_text}]

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
                
                # Проверка reasoning (рассуждений)
                reasoning_delta = getattr(delta, "reasoning_content", None)
                if reasoning_delta:
                    if not is_thinking:
                        is_thinking = True
                        yield ("thinking_start", "Размышление над ответом...", "")
                    thinking_text += reasoning_delta
                
                # Текстовое содержимое
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

            # Сохраняем историю
            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": full_response})

        except Exception as err:
            if is_thinking:
                dt = time.time() - t0
                yield ("thinking_end", f"{dt:.1f}", f"Ошибка во время размышления: {err}")
            
            error_msg = f"❌ **Ошибка OpenCode API:** `{err}`"
            yield ("bot_text", error_msg, "")
