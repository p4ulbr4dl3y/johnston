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

    def _generate_tools(self, user_text: str) -> list[tuple[str, str]]:
        """Генерация вызовов инструментов"""
        text_lower = user_text.lower()
        tools = []
        
        if any(w in text_lower for w in ["создай", "файл", "create", "new"]):
            tools.append(("Create", "/Users/yegor/tui/new_module.py"))
            
        if any(w in text_lower for w in ["прочитай", "посмотри", "read", "скрин", "картинка", "png"]):
            tools.append(("Read", "/var/folders/lg/x662tzs55wj3rpcv4fry_bsm0000gn/T/TemporaryItems/Снимок экрана.png"))
            
        if any(w in text_lower for w in ["измени", "поправь", "edit", "стиль", "tcss", "исправь"]):
            tools.append(("Edit", "/Users/yegor/tui/app.tcss"))
            
        if any(w in text_lower for w in ["запусти", "тест", "bash", "run", "коммит", "git"]):
            tools.append(("Bash", ".venv/bin/python test_app.py"))

        if not tools:
            tools = [
                ("Read", "/Users/yegor/tui/app.py"),
                ("Edit", "/Users/yegor/tui/app.tcss"),
                ("Bash", ".venv/bin/python test_app.py")
            ]

        return tools

    async def stream_steps(self, user_text: str) -> AsyncGenerator[Tuple[str, str, str], None]:
        """Асинхронные шаги выполнения агента (сообщения и вызовы инструментов)"""
        tools = self._generate_tools(user_text)
        
        yield ("intro", "Выполняю задачу...", "")
        await asyncio.sleep(0.15)
        
        for tool_type, target in tools:
            yield ("tool", tool_type, target)
            await asyncio.sleep(0.25)
            
        yield ("outro", "Все действия завершены успешно!", "")
