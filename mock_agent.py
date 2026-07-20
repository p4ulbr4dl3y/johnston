import asyncio
import random
from typing import AsyncGenerator

PERSONAS = {
    "assistant": {
        "name": "🤖 AI Assistant",
        "description": "Полезный универсальный ассистент",
        "system": "Я универсальный ИИ-ассистент. Готов помочь с ответами на любые вопросы."
    },
    "coder": {
        "name": "💻 Code Guru",
        "description": "Эксперт по коду Python, Rust, TS и Textual",
        "system": "Я опытный разработчик. Могу подсказать паттерны программирования и написать чистый код."
    },
    "philosopher": {
        "name": "🧠 Сократ",
        "description": "Глубокий мыслитель и философ",
        "system": "Я мыслю, следовательно, вы спрашиваете. Вглядимся в суть бытия."
    },
    "caveman": {
        "name": "🦴 Пещерный Чел",
        "description": "Говорит кратко, без лишних слов",
        "system": "Мало слов. Много толку. Суть тут."
    }
}

RESPONSES = {
    "assistant": [
        "Отличный вопрос! Давайте разберем его по шагам.\n\nTextual позволяет строить **богатые консольные интерфейсы** с реактивным состоянием и поддержкой асинхронного выполнения.\n\n* Преимущество 1: Скорость работы\n* Преимущество 2: Кроссплатформенность\n* Преимущество 3: Стиль через TCSS",
        "Понял задачу. Все компоненты готовы к работе. Чем еще могу помочь?",
        "Вот что думает ИИ по этому поводу:\n\n1. Начните с простых компонентов (`Static`, `Button`, `Input`).\n2. Используйте `@work` для фоновых задач.\n3. Стилизуйте приложение через `.tcss` файл."
    ],
    "coder": [
        """Вот пример кода на Python с использованием Textual:

```python
from textual.app import App, ComposeResult
from textual.widgets import Label

class SimpleApp(App):
    def compose(self) -> ComposeResult:
        yield Label('Hello, Textual!')

if __name__ == '__main__':
    SimpleApp().run()
```

Этот код запускает базовое TUI приложение.""",
        "Архитектурный совет:\n- Разделяйте UI логику (Widgets) и бизнес-логику.\n- Используйте `reactive` переменные для авто-обновления виджетов.",
        "Ошибок в синтаксисе не обнаружено. Код работает за `O(1)`."
    ],
    "philosopher": [
        "Вопрос звучит просто, но какова его глубокая природа?\n\n> *Знание — это лишь мост между неизвестным вчера и непонятым завтра.*",
        "Что есть терминалия? Не изображение ли это чистой мысли в моноширинных символах?",
        "Все вещи стремятся к упорядоченности. Чат-интерфейс — лишь способ связать умы через пиксели."
    ],
    "caveman": [
        "Понял. Делаю. Баг пофиксен -> все работает.",
        "Проблема в async. Забыли `await`. Добавить `await` -> профит.",
        "Код готов. Запуск `.venv/bin/python app.py`. Готово."
    ]
}

class MockAgent:
    def __init__(self, persona_key: str = "assistant"):
        self.persona_key = persona_key

    def set_persona(self, persona_key: str):
        if persona_key in PERSONAS:
            self.persona_key = persona_key

    async def stream_response(self, user_text: str) -> AsyncGenerator[str, None]:
        """Имитация потокового ответа по словам/символам."""
        responses = RESPONSES.get(self.persona_key, RESPONSES["assistant"])
        base_reply = random.choice(responses)
        
        prefix = f"Ответ на «*{user_text.strip()}*»:\n\n" if len(user_text) < 40 else ""
        full_text = prefix + base_reply
        
        tokens = full_text.split(" ")
        for i, token in enumerate(tokens):
            yield token + (" " if i < len(tokens) - 1 else "")
            await asyncio.sleep(random.uniform(0.03, 0.09))
