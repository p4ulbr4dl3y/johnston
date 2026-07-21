from textual.widgets import TextArea
from textual.message import Message
from textual import events

class ChatInput(TextArea):
    """Поле ввода с реактивными подсказками при реальном вводе символов"""

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

    def load_text(self, text: str) -> None:
        super().load_text(text)
        self._on_input_change()

    def update_height(self) -> None:
        """Динамический расчет высоты от 2 до 8 строк"""
        lines = len(self.text.split("\n"))
        target_height = max(2, min(lines + 1, 8))
        h = self.styles.height
        if h is None or h.value != target_height or str(getattr(h, "unit", "")) != "Unit.CELLS":
            self.styles.height = target_height

    def update_suggestions(self) -> None:
        """Обновление списка подсказок слэш-команд"""
        if self.app:
            try:
                from widgets.command_suggestions import CommandSuggestions
                suggestions = self.app.query_one("#command-suggestions", CommandSuggestions)
                suggestions.update_query(self.text)
            except Exception as e:
                pass

    def _on_input_change(self) -> None:
        """Вызывается при любом изменении текста в инпуте"""
        self.update_height()
        self.update_suggestions()

    def add_to_history(self, text: str) -> None:
        """Сохранение отправленного сообщения в историю запросов"""
        if text and (not self.prompt_history or self.prompt_history[-1] != text):
            self.prompt_history.append(text)
        self.prompt_history_index = len(self.prompt_history)
        self.prompt_draft = ""

    def _on_key(self, event: events.Key) -> None:
        # Горячие клавиши выхода (Ctrl+C, Ctrl+Q)
        if event.key in ("ctrl+c", "ctrl+q"):
            event.prevent_default()
            event.stop()
            self.app.exit()
            return

        # Отмена активной генерации агента по Escape
        if event.key == "escape":
            active_workers = [w for w in self.app.workers if w.is_running]
            if active_workers:
                for w in active_workers:
                    w.cancel()
                event.prevent_default()
                event.stop()
                return

        # Нажатие Tab для автодополнения слэш-команды или переключения режимов (Plan/Build)
        if event.key == "tab":
            try:
                from widgets.command_suggestions import CommandSuggestions, COMMANDS
                suggestions = self.app.query_one("#command-suggestions", CommandSuggestions)
                if suggestions.display and suggestions.highlighted is not None:
                    matched_cmds = [cmd for cmd, _ in COMMANDS if cmd.startswith(self.text.strip().lower())]
                    if suggestions.highlighted < len(matched_cmds):
                        chosen_cmd = matched_cmds[suggestions.highlighted]
                        self.load_text(chosen_cmd)
                        lines = self.text.split("\n")
                        self.move_cursor((len(lines) - 1, len(lines[-1])))
                        suggestions.display = False
                        event.prevent_default()
                        event.stop()
                        return
            except Exception:
                pass

            event.prevent_default()
            event.stop()
            if hasattr(self.app, "agent") and self.app.agent:
                curr = getattr(self.app.agent, "mode", "build")
                new_mode = "build" if curr == "plan" else "plan"
                self.app.agent.mode = new_mode
                if hasattr(self.app, "refresh_status_footer"):
                    self.app.refresh_status_footer()
                self.app.notify(f"Mode switched: {new_mode.upper()}")
            return

        # Обработка навигации в меню подсказок по стрелкам
        try:
            from widgets.command_suggestions import CommandSuggestions
            suggestions = self.app.query_one("#command-suggestions", CommandSuggestions)
            if suggestions.display:
                if event.key == "up":
                    suggestions.action_cursor_up()
                    event.prevent_default()
                    event.stop()
                    return
                elif event.key == "down":
                    suggestions.action_cursor_down()
                    event.prevent_default()
                    event.stop()
                    return
        except Exception:
            pass

        # Зацикленная навигация по истории запросов: Вверх
        if event.key == "up" and self.cursor_location[0] == 0:
            if self.prompt_history:
                if self.prompt_history_index == len(self.prompt_history):
                    self.prompt_draft = self.text
                
                if self.prompt_history_index == 0:
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

        # Зацикленная навигация по истории запросов: Вниз
        lines = self.text.split("\n")
        if event.key == "down" and self.cursor_location[0] == len(lines) - 1:
            if self.prompt_history:
                if self.prompt_history_index == len(self.prompt_history):
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
            event.prevent_default()
            event.stop()
            
            # Скрываем подсказки
            try:
                from widgets.command_suggestions import CommandSuggestions
                suggestions = self.app.query_one("#command-suggestions", CommandSuggestions)
                suggestions.display = False
            except Exception:
                pass

            text = self.text
            self.add_to_history(text)
            self.load_text("")
            self.post_message(self.Submitted(text))
        elif event.key in ("ctrl+enter", "ctrl+j", "shift+enter"):
            event.prevent_default()
            event.stop()
            self.insert("\n")
            self._on_input_change()
        else:
            # На ЛЮБОЕ нажатие клавиши вызываем перерасчет после рефреша
            self.call_after_refresh(self._on_input_change)
