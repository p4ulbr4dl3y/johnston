import asyncio
import random
from typing import AsyncGenerator

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

    def _generate_tool_calls(self, user_text: str) -> list[str]:
        """Генерация вызовов инструментов в формате пользователя"""
        text_lower = user_text.lower()
        tools = []
        
        if any(w in text_lower for w in ["создай", "файл", "create", "new"]):
            tools.append("● Create(/Users/yegor/tui/new_module.py)")
            
        if any(w in text_lower for w in ["прочитай", "посмотри", "read", "скрин", "картинка", "png"]):
            tools.append("● Read(/var/folders/lg/x662tzs55wj3rpcv4fry_bsm0000gn/T/TemporaryItems/Снимок экрана.png)")
            
        if any(w in text_lower for w in ["измени", "поправь", "edit", "стиль", "tcss", "исправь"]):
            tools.append("● Edit(/Users/yegor/tui/app.tcss)")
            
        if any(w in text_lower for w in ["запусти", "тест", "bash", "run", "коммит", "git"]):
            tools.append("● Bash(.venv/bin/python test_app.py)")

        # Если явных ключевых слов нет, генерируем стандартный набор вызовов
        if not tools:
            tools = [
                "● Read(/Users/yegor/tui/app.py)",
                "● Edit(/Users/yegor/tui/app.tcss)",
                "● Bash(.venv/bin/python test_app.py)"
            ]

        return tools

    async def stream_response(self, user_text: str) -> AsyncGenerator[str, None]:
        """Имитация потокового ответа агента с вызовом инструментов"""
        tools = self._generate_tool_calls(user_text)
        tool_section = "\n".join(tools)
        
        reply_templates = [
            f"Выполняю задачу:\n\n{tool_section}\n\nВсе действия завершены успешно! Результат готов.",
            f"Анализирую запрос:\n\n{tool_section}\n\nИзменения внесены и проверены автотестами.",
            f"Запускаю обработку:\n\n{tool_section}\n\nКод обновлен, ошибки не обнаружены."
        ]
        
        full_text = random.choice(reply_templates)
        
        # Разбиваем на слова/токены для асинхронной анимации
        tokens = full_text.split(" ")
        for i, token in enumerate(tokens):
            yield token + (" " if i < len(tokens) - 1 else "")
            await asyncio.sleep(random.uniform(0.02, 0.06))
