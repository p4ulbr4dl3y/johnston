import asyncio
import random
from typing import AsyncGenerator, Tuple

PERSONAS = {
    "assistant": {
        "name": "🤖 AI Assistant",
        "description": "Полезный универсальный ассистент",
        "system": "Я универсальный ИИ-ассистент. Использую инструменты Create, Read, Edit, Bash."
    },
    "coder": {
        "name": "💻 Code Guru",
        "description": "Эксперт по коду Python, Rust, TS и Textual",
        "system": "Я опытный разработчик. Пишу код и выполняю команды."
    },
    "philosopher": {
        "name": "🧠 Сократ",
        "description": "Глубокий мыслитель и философ",
        "system": "Я мыслю, следовательно, вы спрашиваете."
    },
    "caveman": {
        "name": "🦴 Пещерный Чел",
        "description": "Говорит кратко, без лишних слов",
        "system": "Мало слов. Много толку."
    }
}

class MockAgent:
    def __init__(self, persona_key: str = "assistant"):
        self.persona_key = persona_key

    def set_persona(self, persona_key: str):
        if persona_key in PERSONAS:
            self.persona_key = persona_key

    async def stream_steps(self, user_text: str) -> AsyncGenerator[Tuple[str, str, str], None]:
        """Генерация цепочки действий с форматированием Markdown в рассуждениях и ответах"""
        
        # 1. Первичное думание с Markdown (списки, жирный текст)
        t1_details = (
            f"**Анализ запроса:** «{user_text.strip()}»\n\n"
            "* **Шаг 1**: Проверка структуры проекта\n"
            "* **Шаг 2**: Подготовка конфигурации `Textual`"
        )
        yield ("thinking_start", t1_details, "")
        
        t0 = asyncio.get_running_loop().time()
        await asyncio.sleep(1.2)
        dt1 = asyncio.get_running_loop().time() - t0
        yield ("thinking_end", f"{dt1:.1f}", t1_details)
        
        # 2. Инструмент Read
        yield ("tool", "Read", "/Users/yegor/tui/app.py")
        await asyncio.sleep(0.25)
        
        # 3. Текст ИИ с Markdown (цитаты, инлайн-код)
        msg1 = (
            "Файл `app.py` изучен.\n\n"
            "> *Ключевые компоненты:* `TUIChatApp`, `ChatView`, `ThinkingWidget`"
        )
        yield ("bot_text", msg1, "")
        await asyncio.sleep(0.3)
        
        # 4. Вторичное думание с кодом на Python в Markdown
        t2_details = (
            "**Вторичный анализ кода:**\n\n"
            "```python\n"
            "# Проверка стилей\n"
            "styles.margin = (0, 0)\n"
            "styles.height = 'auto'\n"
            "```"
        )
        yield ("thinking_start", t2_details, "")
        
        t1 = asyncio.get_running_loop().time()
        await asyncio.sleep(0.9)
        dt2 = asyncio.get_running_loop().time() - t1
        yield ("thinking_end", f"{dt2:.1f}", t2_details)
        
        # 5. Инструменты Edit и Bash
        yield ("tool", "Edit", "/Users/yegor/tui/app.tcss")
        await asyncio.sleep(0.25)
        yield ("tool", "Bash", ".venv/bin/python test_app.py")
        await asyncio.sleep(0.25)
        
        # 6. Финальный ответ ИИ с Markdown
        msg2 = (
            "Все проверки **успешно пройдены**!\n\n"
            "* Код отформатирован\n"
            "* `Markdown` отрендерен во всех блоках"
        )
        yield ("outro", msg2, "")
