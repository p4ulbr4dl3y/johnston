from textual.widgets import TextArea
from textual.message import Message
from textual import events

class ChatInput(TextArea):
    """Поле ввода с поддержкой Ctrl+Enter для перевода строки и Enter для отправки"""

    class Submitted(Message):
        """Событие отправки текста"""
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            # Выполнение отправки при Enter
            event.prevent_default()
            event.stop()
            text = self.text
            self.load_text("")
            self.post_message(self.Submitted(text))
        elif event.key in ("ctrl+enter", "ctrl+j", "shift+enter"):
            # Ctrl+Enter / Shift+Enter -> вставить перенос строки
            event.prevent_default()
            event.stop()
            self.insert("\n")
