from textual.widgets import TextArea
from textual.message import Message
from textual import events

class ChatInput(TextArea):
    """Поле ввода с зацикленной историей запросов (Стрелки Вверх/Вниз)"""

    class Submitted(Message):
        """Событие отправки текста"""
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prompt_history: list[str] = []
        self.prompt_history_index: int = 0
        self.prompt_draft: str = ""

    def on_mount(self) -> None:
        self.focus()
        self.update_height()

    def on_blur(self, event: events.Blur) -> None:
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

    def add_to_history(self, text: str) -> None:
        """Сохранение отправленного сообщения в историю запросов"""
        if text and (not self.prompt_history or self.prompt_history[-1] != text):
            self.prompt_history.append(text)
        self.prompt_history_index = len(self.prompt_history)
        self.prompt_draft = ""

    def _on_key(self, event: events.Key) -> None:
        # Горячие клавиши выхода (Ctrl+C, Ctrl+Q, Esc)
        if event.key in ("ctrl+c", "ctrl+q", "escape"):
            event.prevent_default()
            event.stop()
            self.app.exit()
            return

        # Зацикленная навигация Вверх
        if event.key == "up" and self.cursor_location[0] == 0:
            if self.prompt_history:
                if self.prompt_history_index == len(self.prompt_history):
                    self.prompt_draft = self.text
                
                if self.prompt_history_index == 0:
                    # Зацикливание: с самого верха в самый низ (к черновику)
                    self.prompt_history_index = len(self.prompt_history)
                    self.load_text(self.prompt_draft)
                else:
                    self.prompt_history_index -= 1
                    self.load_text(self.prompt_history[self.prompt_history_index])
                
                lines = self.text.split("\n")
                self.move_cursor((len(lines) - 1, len(lines[-1])))
                event.prevent_default()
                event.stop()
                return

        # Зацикленная навигация Вниз
        lines = self.text.split("\n")
        if event.key == "down" and self.cursor_location[0] == len(lines) - 1:
            if self.prompt_history:
                if self.prompt_history_index == len(self.prompt_history):
                    # Зацикливание: с самого низа в самый верх (к первому сообщению)
                    self.prompt_draft = self.text
                    self.prompt_history_index = 0
                    self.load_text(self.prompt_history[0])
                else:
                    self.prompt_history_index += 1
                    if self.prompt_history_index == len(self.prompt_history):
                        self.load_text(self.prompt_draft)
                    else:
                        self.load_text(self.prompt_history[self.prompt_history_index])
                
                lines = self.text.split("\n")
                self.move_cursor((len(lines) - 1, len(lines[-1])))
                event.prevent_default()
                event.stop()
                return

        if event.key == "enter":
            # Enter без Ctrl -> отправка
            event.prevent_default()
            event.stop()
            text = self.text
            self.add_to_history(text)
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
