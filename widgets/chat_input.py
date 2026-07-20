from textual.widgets import TextArea
from textual.message import Message
from textual import events

class ChatInput(TextArea):
    """Поле ввода с неразрывным перманентным фокусом и поддержкой комбинаций выхода"""

    class Submitted(Message):
        """Событие отправки текста"""
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def on_mount(self) -> None:
        self.focus()
        self.update_height()

    def on_blur(self, event: events.Blur) -> None:
        """Если фокус потерян, мгновенно возвращаем его обратно"""
        self.call_after_refresh(self.focus)

    def watch_text(self, new_text: str) -> None:
        self.update_height()

    def load_text(self, text: str) -> None:
        super().load_text(text)
        self.update_height()

    def update_height(self) -> None:
        """Динамический расчет высоты от 3 до 10 строк"""
        lines = len(self.text.split("\n"))
        target_height = max(3, min(lines + 2, 10))
        if self.styles.height.value != target_height:
            self.styles.height = target_height

    def _on_key(self, event: events.Key) -> None:
        # Проверяем горячие клавиши выхода (Ctrl+C, Ctrl+Q, Esc)
        if event.key in ("ctrl+c", "ctrl+q", "escape"):
            event.prevent_default()
            event.stop()
            self.app.exit()
            return

        if event.key == "enter":
            # Enter без Ctrl -> отправка
            event.prevent_default()
            event.stop()
            text = self.text
            self.load_text("")
            self.post_message(self.Submitted(text))
        elif event.key in ("ctrl+enter", "ctrl+j", "shift+enter"):
            # Ctrl+Enter / Shift+Enter -> перенос строки
            event.prevent_default()
            event.stop()
            self.insert("\n")
            self.update_height()
        else:
            self.call_after_refresh(self.update_height)
