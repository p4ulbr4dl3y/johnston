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
        """Многошаговая генерация: думание -> инструмент -> текст -> новое думание -> инструмент -> итог"""
        
        # 1. Первичное думание
        t1_details = f"Анализирую запрос «{user_text.strip()}» и проверяю структуру файлов..."
        yield ("thinking_start", t1_details, "")
        
        t0 = asyncio.get_running_loop().time()
        await asyncio.sleep(1.2)
        dt1 = asyncio.get_running_loop().time() - t0
        yield ("thinking_end", f"{dt1:.1f}", t1_details)
        
        # 2. Первое действие
        yield ("tool", "Read", "/Users/yegor/tui/app.py")
        await asyncio.sleep(0.25)
        
        # 3. Текстовый комментарий агента в процессе
        yield ("bot_text", "Файл `app.py` изучен. Перехожу к подготовке изменений.", "")
        await asyncio.sleep(0.3)
        
        # 4. Вторичное думание
        t2_details = "Расчет стилей, проверка зависимостей и подготовка тестового скрипта..."
        yield ("thinking_start", t2_details, "")
        
        t1 = asyncio.get_running_loop().time()
        await asyncio.sleep(0.9)
        dt2 = asyncio.get_running_loop().time() - t1
        yield ("thinking_end", f"{dt2:.1f}", t2_details)
        
        # 5. Выполнение остальных инструментов
        yield ("tool", "Edit", "/Users/yegor/tui/app.tcss")
        await asyncio.sleep(0.25)
        yield ("tool", "Bash", ".venv/bin/python test_app.py")
        await asyncio.sleep(0.25)
        
        # 6. Финальный ответ
        yield ("outro", "Все проверки выполнены успешно! Изменения применены.", "")
