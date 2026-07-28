from textual import events
from textual.message import Message
from textual.widgets import TextArea


class ChatInput(TextArea):
    """Input field with reactive suggestions on character typing"""

    class Submitted(Message):
        """Text submission event"""
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
        from textual.screen import ModalScreen
        if self.app and isinstance(self.app.screen, ModalScreen):
            return
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
        """Dynamic height calculation from 2 to 6 lines"""
        lines = len(self.text.split("\n"))
        target_height = max(2, min(lines + 1, 6))
        h = self.styles.height
        if h is None or h.value != target_height or str(getattr(h, "unit", "")) != "Unit.CELLS":
            self.styles.height = target_height

    def update_suggestions(self) -> None:
        """Update slash command and file suggestions list"""
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
        """Inserts chosen file path after @ symbol"""
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

    def _on_input_change(self) -> None:
        """Called on any input text change"""
        self.update_height()
        self.update_suggestions()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._on_input_change()

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".svg"}

    def format_pasted_file_path(self, pasted_text: str) -> str:
        """Automatically formats pasted file paths as @file"""
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
                new_lines.append(stripped)
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
                    line = f"@{stripped}"
                    modified = True
                new_lines.append(line)

        return "\n".join(new_lines) if modified else pasted_text

    def try_paste_clipboard_image(self) -> bool:
        """Checks clipboard for PNG image and inserts as [Image #N]"""
        import os
        import subprocess
        import time

        try:
            # If clipboard contains a Finder file reference («class furl»), do not treat as raw image paste
            info_res = subprocess.run("osascript -e 'clipboard info'", shell=True, capture_output=True, text=True, timeout=2)
            if info_res.returncode == 0 and "«class furl»" in info_res.stdout:
                return False

            cmd = "osascript -e 'get the clipboard as «class PNGf»'"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and "«data PNGf" in res.stdout:
                raw_hex = res.stdout.strip().split("«data PNGf")[-1].replace("»", "").strip()
                img_bytes = bytes.fromhex(raw_hex)
                if len(img_bytes) > 0:
                    from core.config import TEMP_IMAGES_DIR

                    out_dir = TEMP_IMAGES_DIR
                    os.makedirs(out_dir, exist_ok=True)
                    filepath = os.path.join(out_dir, f"clip_{int(time.time())}.png")
                    with open(filepath, "wb") as f:
                        f.write(img_bytes)

                    img_count = len([k for k in self.pasted_texts if k.startswith("[Image #")]) + 1
                    tag = f"[Image #{img_count}]"
                    self.pasted_texts[tag] = f"@{filepath}"
                    self.insert(tag)
                    self._on_input_change()
                    return True
        except Exception:
            pass

        return False

    def paste_universal_clipboard(self) -> bool:
        """Universal clipboard paste (image or text)"""
        import subprocess

        # 1. Try pasting image from clipboard
        if self.try_paste_clipboard_image():
            return True

        # 2. If no image, read text from clipboard
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
        import os
        text_strip = event.text.strip().strip("'\"")
        expanded = os.path.expanduser(text_strip.replace("\\ ", " "))
        is_path = (
            text_strip.startswith("/")
            or text_strip.startswith("~/")
            or text_strip.startswith("./")
            or text_strip.startswith("file://")
            or os.path.exists(expanded)
        )
        if not is_path and not event.text.strip() and self.try_paste_clipboard_image():
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
        """Save submitted message to query history"""
        if text and (not self.prompt_history or self.prompt_history[-1] != text):
            self.prompt_history.append(text)
        self.prompt_history_index = len(self.prompt_history)
        self.prompt_draft = ""

    def _handle_tag_deletion(self, event_key: str) -> bool:
        """Atomic deletion of [Pasted text #N +X lines] block on Backspace or Delete"""
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
        # Atomic deletion of pasted block via Backspace/Delete
        if event.key in ("backspace", "delete"):
            if self._handle_tag_deletion(event.key):
                event.prevent_default()
                event.stop()
                return

        # Global Exit shortcut: Ctrl+C / Ctrl+Q
        if event.key in ("ctrl+c", "ctrl+q"):
            event.prevent_default()
            event.stop()
            self.app.exit()
            return

        # Cancel active suggestions popup or agent generation via Escape
        if event.key == "escape":
            try:
                from widgets.command_suggestions import CommandSuggestions
                suggestions = self.app.query_one("#command-suggestions", CommandSuggestions)
                if suggestions.display:
                    suggestions.display = False
                    event.prevent_default()
                    event.stop()
                    return
            except Exception:
                pass

            active_workers = [w for w in self.app.workers if w.is_running]
            if active_workers:
                for w in active_workers:
                    w.cancel()
                event.prevent_default()
                event.stop()
                return

        # Tab press for slash command or file autocompletion
        if event.key == "tab":
            try:
                from widgets.command_suggestions import CommandSuggestions
                suggestions = self.app.query_one("#command-suggestions", CommandSuggestions)
                if suggestions.display and suggestions.highlighted is not None:
                    if suggestions.mode == "command":
                        if suggestions.highlighted < len(suggestions.current_matched):
                            chosen_cmd = suggestions.current_matched[suggestions.highlighted]
                            self.load_text(chosen_cmd + " ")
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

        # Shift+Tab press to toggle mode (Action / Explore)
        if event.key in ("shift+tab", "backtab", "shift_tab"):
            event.prevent_default()
            event.stop()
            if hasattr(self.app, "action_toggle_mode"):
                self.app.action_toggle_mode()
            return

        # Handle arrow navigation in suggestions menu
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

        # Looped navigation through query history: Up
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

        # Looped navigation through query history: Down
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
            # Select suggestion if suggestion menu is open
            try:
                from widgets.command_suggestions import CommandSuggestions
                suggestions = self.app.query_one("#command-suggestions", CommandSuggestions)
                if suggestions.display and suggestions.highlighted is not None:
                    if suggestions.mode == "command":
                        if suggestions.highlighted < len(suggestions.current_matched):
                            chosen_cmd = suggestions.current_matched[suggestions.highlighted]
                            self.load_text(chosen_cmd + " ")
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

            event.prevent_default()
            event.stop()

            # Hide suggestions
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
            # On ANY keypress invoke recalculation after refresh
            self.call_after_refresh(self._on_input_change)
