from textual import events
from textual.message import Message
from textual.widgets import TextArea


class ChatInput(TextArea):
    """Поле ввода с реактивными подсказками при реальном вводе символов"""

    class Submitted(Message):
        """Событие отправки текста"""
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    PASTE_LINE_THRESHOLD = 10

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prompt_history: list[str] = []
        self.prompt_history_index: int = 0
        self.prompt_draft: str = ""
        self.pasted_texts: dict[str, str] = {}

    def on_mount(self) -> None:
        self.focus()
        self.update_height()

    def on_blur(self, event: events.Blur) -> None:
        self.call_after_refresh(self.focus)

    def load_text(self, text: str) -> None:
        if not text:
            self.pasted_texts.clear()
        super().load_text(text)
        self._on_input_change()

    def get_full_text(self) -> str:
        text = self.text
        for tag, raw_val in self.pasted_texts.items():
            if tag in text:
                text = text.replace(tag, raw_val)
        return text

    def update_height(self) -> None:
        """Динамический расчет высоты от 2 до 8 строк"""
        lines = len(self.text.split("\n"))
        target_height = max(2, min(lines + 1, 8))
        h = self.styles.height
        if h is None or h.value != target_height or str(getattr(h, "unit", "")) != "Unit.CELLS":
            self.styles.height = target_height

    def update_suggestions(self) -> None:
        """Обновление списка подсказок слэш-команд и файлов"""
        try:
            if self.is_mounted and self.app:
                from widgets.command_suggestions import CommandSuggestions
                suggestions = self.app.query_one("#command-suggestions", CommandSuggestions)
                row, col = self.cursor_location
                line_str = self.document.get_line(row)
                suggestions.update_query(self.text, line_str, col)
        except Exception:
            pass

    def apply_file_suggestion(self, chosen_file: str, at_start_idx: int) -> None:
        """Вставляет выбранный путь к файлу после символа @"""
        row, col = self.cursor_location
        line_str = self.document.get_line(row)
        before = line_str[:at_start_idx]
        after = line_str[col:]
        inserted = f"@{chosen_file} "
        new_line = before + inserted + after

        lines = self.text.split("\n")
        lines[row] = new_line
        self.load_text("\n".join(lines))

        new_col = at_start_idx + len(inserted)
        self.move_cursor((row, new_col))

    def auto_format_image_tags(self) -> None:
        """Сканирует текст инпута на наличие путей к изображениям и заменяет их на [Image #N]"""
        import os
        import re

        text = self.text
        if not text:
            return

        pattern = r'(@?(?:/[^\s]+|~/[^\s]+|file://[^\s]+|\S+\.(?:png|jpg|jpeg|gif|webp|bmp|ico|tiff|svg)))'
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if not matches:
            return

        modified = False
        new_text = text

        for raw_match in matches:
            clean = raw_match.lstrip("@").strip("'\"").replace("\\ ", " ")
            expanded = os.path.expanduser(clean)
            ext = os.path.splitext(clean)[1].lower()

            if ext in self.IMAGE_EXTENSIONS and (os.path.exists(expanded) or raw_match.startswith("/") or raw_match.startswith("~/") or raw_match.startswith("file://")):
                existing_tag = None
                for tag, val in self.pasted_texts.items():
                    if tag.startswith("[Image #") and (val == raw_match or val == f"@{clean}" or val == f"@{raw_match.lstrip('@')}"):
                        existing_tag = tag
                        break

                if not existing_tag:
                    img_count = len([k for k in self.pasted_texts if k.startswith("[Image #")]) + 1
                    existing_tag = f"[Image #{img_count}]"
                    self.pasted_texts[existing_tag] = f"@{clean}"

                new_text = new_text.replace(raw_match, existing_tag)
                modified = True

        if modified and new_text != self.text:
            row, col = self.cursor_location
            self.load_text(new_text)
            lines = new_text.split("\n")
            self.move_cursor((min(row, len(lines) - 1), len(lines[-1])))

    def _on_input_change(self) -> None:
        """Вызывается при любом изменении текста в инпуте"""
        self.update_height()
        self.update_suggestions()
        self.auto_format_image_tags()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._on_input_change()

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".svg"}

    def format_pasted_file_path(self, pasted_text: str) -> str:
        """Автоматически форматирует вставленные пути к файлам (@file или [Image #N])"""
        import os
        lines = pasted_text.strip().splitlines()
        if not lines:
            return pasted_text

        new_lines = []
        modified = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                new_lines.append(line)
                continue

            if stripped.startswith("@"):
                path_part = stripped[1:]
                clean = path_part.strip("'\"").replace("\\ ", " ")
                expanded = os.path.expanduser(clean)
                ext = os.path.splitext(clean)[1].lower()
                if ext in self.IMAGE_EXTENSIONS and os.path.exists(expanded):
                    img_count = len([k for k in self.pasted_texts if k.startswith("[Image #")]) + 1
                    tag = f"[Image #{img_count}]"
                    self.pasted_texts[tag] = stripped
                    line = tag
                    modified = True
            else:
                clean = stripped.strip("'\"").replace("\\ ", " ")
                expanded = os.path.expanduser(clean)
                ext = os.path.splitext(clean)[1].lower()
                is_explicit_path = (
                    stripped.startswith("/")
                    or stripped.startswith("~/")
                    or stripped.startswith("./")
                    or stripped.startswith("file://")
                )
                if is_explicit_path or ((bool(ext) or "/" in clean) and os.path.exists(expanded)):
                    if ext in self.IMAGE_EXTENSIONS:
                        img_count = len([k for k in self.pasted_texts if k.startswith("[Image #")]) + 1
                        tag = f"[Image #{img_count}]"
                        self.pasted_texts[tag] = f"@{stripped}"
                        line = tag
                    else:
                        line = f"@{stripped}"
                    modified = True

            new_lines.append(line)

        if modified:
            return "\n".join(new_lines)
        return pasted_text

    def try_paste_clipboard_image(self) -> bool:
        """Проверяет буфер обмена на наличие PNG изображения и вставляет его как [Image #N]"""
        import os
        import subprocess
        import time

        try:
            cmd = "osascript -e 'get the clipboard as «class PNGf»'"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and "«data PNGf" in res.stdout:
                raw_hex = res.stdout.strip().split("«data PNGf")[-1].replace("»", "").strip()
                img_bytes = bytes.fromhex(raw_hex)
                if len(img_bytes) > 0:
                    out_dir = os.path.expanduser("~/.johnston/temp_images")
                    os.makedirs(out_dir, exist_ok=True)
                    filepath = os.path.join(out_dir, f"clip_{int(time.time())}.png")
                    with open(filepath, "wb") as f:
                        f.write(img_bytes)

                    img_count = len([k for k in self.pasted_texts if k.startswith("[Image #")]) + 1
                    tag = f"[Image #{img_count}]"
                    self.pasted_texts[tag] = f"@{filepath}"
                    self.insert(tag)
                    self._on_input_change()
                    if self.app:
                        self.app.notify("Pasted image from clipboard!")
                    return True
        except Exception:
            pass

        return False

    def paste_universal_clipboard(self) -> bool:
        """Универсальная вставка из буфера обмена (картинка или текст)"""
        import subprocess

        # 1. Пробуем вставить картинку из буфера
        if self.try_paste_clipboard_image():
            return True

        # 2. Если картинки нет, считываем текст из буфера обмена
        try:
            res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout:
                text_content = res.stdout
                pasted_text = self.format_pasted_file_path(text_content)
                lines = pasted_text.splitlines()

                if len(lines) > self.PASTE_LINE_THRESHOLD:
                    idx = len(self.pasted_texts) + 1
                    tag = f"[Pasted text #{idx} +{len(lines)} lines]"
                    self.pasted_texts[tag] = pasted_text
                    self.insert(tag)
                else:
                    self.insert(pasted_text)

                self._on_input_change()
                return True
        except Exception:
            pass

        return False

    def on_paste(self, event: events.Paste) -> None:
        if self.try_paste_clipboard_image():
            event.prevent_default()
            event.stop()
            return

        pasted_text = self.format_pasted_file_path(event.text)
        lines = pasted_text.splitlines()
        if len(lines) > self.PASTE_LINE_THRESHOLD:
            event.prevent_default()
            event.stop()
            idx = len(self.pasted_texts) + 1
            tag = f"[Pasted text #{idx} +{len(lines)} lines]"
            self.pasted_texts[tag] = pasted_text
            self.insert(tag)
            self._on_input_change()
        else:
            event.prevent_default()
            event.stop()
            self.insert(pasted_text)
            self._on_input_change()

    def add_to_history(self, text: str) -> None:
        """Сохранение отправленного сообщения в историю запросов"""
        if text and (not self.prompt_history or self.prompt_history[-1] != text):
            self.prompt_history.append(text)
        self.prompt_history_index = len(self.prompt_history)
        self.prompt_draft = ""

    def _handle_tag_deletion(self, event_key: str) -> bool:
        """Атомарное удаление блока [Pasted text #N +X lines] при нажатии Backspace или Delete"""
        if not self.pasted_texts or not self.selection.is_empty:
            return False

        row, col = self.cursor_location
        line_str = self.document.get_line(row)

        for tag in list(self.pasted_texts.keys()):
            start_col = line_str.find(tag)
            while start_col != -1:
                end_col = start_col + len(tag)
                if event_key == "backspace" and start_col < col <= end_col:
                    self.delete((row, start_col), (row, end_col))
                    self.move_cursor((row, start_col))
                    self.pasted_texts.pop(tag, None)
                    self._on_input_change()
                    return True
                elif event_key == "delete" and start_col <= col < end_col:
                    self.delete((row, start_col), (row, end_col))
                    self.move_cursor((row, start_col))
                    self.pasted_texts.pop(tag, None)
                    self._on_input_change()
                    return True
                start_col = line_str.find(tag, start_col + 1)

        return False

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("ctrl+v", "cmd+v", "ctrl+м", "ctrl+m"):
            if self.try_paste_clipboard_image():
                event.prevent_default()
                event.stop()
                return
        # Атомарное удаление блока вставки по Backspace/Delete
        if event.key in ("backspace", "delete"):
            if self._handle_tag_deletion(event.key):
                event.prevent_default()
                event.stop()
                return

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

        # Нажатие Tab для автодополнения слэш-команды или файла
        if event.key == "tab":
            try:
                from widgets.command_suggestions import CommandSuggestions
                suggestions = self.app.query_one("#command-suggestions", CommandSuggestions)
                if suggestions.display and suggestions.highlighted is not None:
                    if suggestions.mode == "command":
                        if suggestions.highlighted < len(suggestions.current_matched):
                            chosen_cmd = suggestions.current_matched[suggestions.highlighted]
                            self.load_text(chosen_cmd)
                            lines = self.text.split("\n")
                            self.move_cursor((len(lines) - 1, len(lines[-1])))
                            suggestions.display = False
                            event.prevent_default()
                            event.stop()
                            return
                    elif suggestions.mode == "file":
                        if suggestions.highlighted < len(suggestions.current_matched):
                            chosen_file = suggestions.current_matched[suggestions.highlighted]
                            self.apply_file_suggestion(chosen_file, suggestions.at_start_idx)
                            suggestions.display = False
                            event.prevent_default()
                            event.stop()
                            return
            except Exception:
                pass

        # Нажатие Shift+Tab для переключения режимов (Plan/Build)
        if event.key in ("shift+tab", "backtab", "shift_tab"):
            event.prevent_default()
            event.stop()
            if hasattr(self.app, "agent") and self.app.agent:
                curr = getattr(self.app.agent, "mode", "build")
                new_mode = "build" if curr == "plan" else "plan"
                self.app.agent.mode = new_mode
                if hasattr(self.app, "refresh_status_footer"):
                    self.app.refresh_status_footer()
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

            text = self.get_full_text()
            self.pasted_texts.clear()
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
