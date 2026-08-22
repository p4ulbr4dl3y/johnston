import asyncio
import os
import re
import urllib.parse

from textual import events
from textual.message import Message
from textual.widgets import TextArea

from core.infrastructure.platform import paths as config
from core.infrastructure.platform.paths import IMAGE_EXTENSIONS
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json
from widgets.presentation.screens.constants import COMMAND_SUGGESTIONS, STATUS_FOOTER
from widgets.utils.key_aliases import KEY_DETACH, KEY_NEWLINE, KEY_PASTE, KEY_QUIT, KEY_TOGGLE_ROLE

MOUSE_ARTIFACT_REGEX = re.compile(r"(?:M|\[)?<[0-9]{1,3};[0-9]+;[0-9]+[Mm]")


class ClipboardAttachment:
    """Represents a clipboard image attachment"""

    def __init__(self, path: str):
        self.path = path


class ChatInput(TextArea):
    """Input field with reactive suggestions on character typing"""

    class Submitted(Message):
        """Text submission event"""

        def __init__(self, value: str, attachments: list = None) -> None:
            super().__init__()
            self.value = value
            self.attachments = list(attachments or [])

    PASTE_LINE_THRESHOLD = 10

    MAX_PROMPT_HISTORY = 500

    def __init__(self, **kwargs):
        kwargs.setdefault("soft_wrap", True)
        super().__init__(**kwargs)
        self.pasted_texts: dict[str, str] = {}
        self.clipboard_attachments: list = []
        self.prompt_history: list[str] = self.load_prompt_history()
        self.prompt_history_index: int = len(self.prompt_history)
        self.prompt_draft: str = ""

    def load_prompt_history(self) -> list[str]:
        """Load global prompt history from disk"""
        data = read_json(config.PROMPT_HISTORY_FILE, default=[])
        if isinstance(data, list):
            return [str(item) for item in data][-self.MAX_PROMPT_HISTORY :]
        return []

    def _save_prompt_history_to_disk(self, history: list[str]) -> None:
        try:
            atomic_write_json(config.PROMPT_HISTORY_FILE, history[-self.MAX_PROMPT_HISTORY :], indent=2)
        except Exception:
            pass

    def save_prompt_history(self) -> None:
        """Save global prompt history to disk asynchronously off the event loop."""
        history_copy = list(self.prompt_history)
        try:
            loop = asyncio.get_running_loop()
            prev_task = getattr(self, "_save_task", None)

            async def _do_save():
                if prev_task and not prev_task.done():
                    try:
                        await prev_task
                    except Exception:
                        pass
                await asyncio.to_thread(self._save_prompt_history_to_disk, history_copy)

            self._save_task = loop.create_task(_do_save())
        except RuntimeError:
            self._save_prompt_history_to_disk(history_copy)

    def on_mount(self) -> None:
        self.focus()
        self.update_height()

    def load_text(self, text: str) -> None:
        if text is None:
            text = ""
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
        """Dynamic height calculation from 2 to 6 lines, taking wrapped lines into account"""
        raw_lines = len(self.text.split("\n"))
        wrapped_lines = getattr(self.wrapped_document, "height", 1) if hasattr(self, "wrapped_document") else 1
        lines = max(raw_lines, wrapped_lines)
        target_height = max(2, min(lines + 1, 6))
        h = self.styles.height
        if h is None or h.value != target_height or str(getattr(h, "unit", "")) != "Unit.CELLS":
            self.styles.height = target_height

        try:
            if self.is_mounted and self.app:
                from widgets.command_suggestions import CommandSuggestions

                has_attachments = bool(getattr(self, "clipboard_attachments", None))
                att_offset = 1 if has_attachments else 0
                footer_offset = 2
                margin_b = target_height + footer_offset + att_offset

                sugg = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
                sugg.styles.margin = (0, 0, margin_b, 0)
        except Exception:
            pass

    async def update_suggestions(self) -> None:
        """Update slash command and file suggestions list"""
        try:
            if self.is_mounted and self.app:
                from widgets.command_suggestions import CommandSuggestions

                suggestions = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
                row, col = self.cursor_location
                line_str = self.document.get_line(row)
                await suggestions.update_query(self.text, line_str, col)
        except Exception:
            pass

    def apply_file_suggestion(self, chosen_file: str, at_start_idx: int) -> None:
        """Inserts chosen file path after @ symbol"""
        prefix = "@" if not chosen_file.startswith("@") else ""
        self.apply_suggestion(f"{prefix}{chosen_file}", at_start_idx)

    def apply_suggestion(self, inserted_text: str, start_idx: int) -> None:
        """Inserts chosen suggestion at start_idx with a trailing space"""
        row, col = self.cursor_location
        line_str = self.document.get_line(row)
        before = line_str[:start_idx]
        after = line_str[col:]
        inserted = inserted_text if inserted_text.endswith(" ") else f"{inserted_text} "
        new_line = before + inserted + after

        lines = self.text.split("\n")
        lines[row] = new_line
        self.load_text("\n".join(lines))

        new_col = start_idx + len(inserted)
        self.move_cursor((row, new_col))

    def sanitize_mouse_artifacts(self) -> None:
        """Strips accidental raw ANSI mouse tracking escape sequences from the text buffer"""
        text = self.text
        if MOUSE_ARTIFACT_REGEX.search(text):
            clean_text = MOUSE_ARTIFACT_REGEX.sub("", text)
            row, col = self.cursor_location
            self.load_text(clean_text)
            lines = clean_text.split("\n")
            max_row = max(0, len(lines) - 1)
            target_row = min(row, max_row)
            target_col = min(col, len(lines[target_row]))
            self.move_cursor((target_row, target_col))

    def _schedule_suggestions_update(self) -> None:
        """Schedule suggestion refresh off the event loop when mounted."""
        if not getattr(self, "is_mounted", False):
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.update_suggestions())
        except RuntimeError:
            pass

    def _on_input_change(self) -> None:
        """Called on any input text change"""
        self.sanitize_mouse_artifacts()
        self.update_height()
        self._schedule_suggestions_update()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._on_input_change()

    def _decode_pasted_path(self, text: str) -> str:
        """Decode a pasted file path: strip quotes, unquote file:/// URLs, expand user dirs."""
        text_strip = text.strip().strip("'\"")
        if text_strip.startswith("file://"):
            text_strip = urllib.parse.unquote(text_strip[7:])
        else:
            text_strip = urllib.parse.unquote(text_strip)
        return os.path.expanduser(text_strip.replace("\\ ", " "))

    def format_pasted_file_path(self, pasted_text: str) -> str:
        """Automatically formats pasted file paths as @file"""
        if pasted_text is None:
            return None
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
                if not stripped.endswith(" "):
                    stripped = stripped + " "
                    modified = True
                new_lines.append(stripped)
            else:
                clean = self._decode_pasted_path(stripped)
                ext = os.path.splitext(clean)[1].lower()
                is_explicit_path = clean.startswith("/") or clean.startswith("~/") or clean.startswith("./")
                if is_explicit_path or ((bool(ext) or "/" in clean) and os.path.exists(clean)):
                    line = f"@{clean} "
                    modified = True
                new_lines.append(line)

        return "\n".join(new_lines) if modified else pasted_text

    def update_attachment_bar(self) -> None:
        try:
            if self.is_mounted and self.app:
                from widgets.presentation.widgets.attachment_bar import AttachmentBar

                bar = self.app.query_one("#attachment-bar", AttachmentBar)
                bar.update_attachments(self.clipboard_attachments)
        except Exception:
            pass
        try:
            if self.is_mounted and self.app:
                footer = self.app.query_one(STATUS_FOOTER)
                footer.refresh_footer()
        except Exception:
            pass

    def remove_clipboard_attachment(self, attachment) -> None:
        """Removes a single attachment and cleans up its temp file."""
        if attachment in self.clipboard_attachments:
            if hasattr(attachment, "path") and os.path.exists(attachment.path) and "temp_images" in attachment.path:
                try:
                    os.remove(attachment.path)
                except OSError:
                    pass
            self.clipboard_attachments.remove(attachment)
            self.update_attachment_bar()

    def clear_clipboard_attachments(self) -> None:
        for att in list(self.clipboard_attachments):
            if os.path.exists(att.path) and "temp_images" in att.path:
                try:
                    os.remove(att.path)
                except OSError:
                    pass
        self.clipboard_attachments.clear()
        self.update_attachment_bar()

    async def try_paste_clipboard_image(self) -> bool:
        """Checks clipboard for PNG/TIFF/JPEG image or Finder/Explorer image file and inserts as attachment"""
        import time

        from core.infrastructure.platform.paths import TEMP_IMAGES_DIR
        from core.infrastructure.platform.platform_utils import get_clipboard_image_or_file

        file_path, img = await asyncio.to_thread(get_clipboard_image_or_file)

        if file_path:
            self.insert(f"@{file_path} ")
            self._on_input_change()
            return True

        if img:
            out_dir = TEMP_IMAGES_DIR
            os.makedirs(out_dir, exist_ok=True)
            final_path = os.path.join(out_dir, f"clip_{int(time.time())}.png")
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            await asyncio.to_thread(img.save, final_path, format="PNG")
            att = ClipboardAttachment(final_path)
            self.clipboard_attachments.append(att)
            self.update_attachment_bar()
            return True

        return False

    async def on_paste(self, event: events.Paste) -> None:
        event.prevent_default()
        event.stop()

        pasted_text = self.format_pasted_file_path(event.text)
        if pasted_text.startswith("@") or (
            pasted_text != event.text
            and any(line_item.strip().startswith("@") for line_item in pasted_text.splitlines())
        ):
            self.insert(pasted_text)
            self._on_input_change()
            return

        expanded = self._decode_pasted_path(event.text)
        exists = await asyncio.to_thread(os.path.exists, expanded)
        is_existing_image_path = exists and any(expanded.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)

        if not is_existing_image_path and not event.text.strip():
            if await self.try_paste_clipboard_image():
                return

        lines = pasted_text.splitlines()
        if len(lines) > self.PASTE_LINE_THRESHOLD:
            idx = len(self.pasted_texts) + 1
            tag = f"[Pasted text #{idx} +{len(lines)} lines]"
            self.pasted_texts[tag] = pasted_text
            self.insert(tag)
        else:
            self.insert(pasted_text)
        self._on_input_change()

    def add_to_history(self, text: str) -> None:
        """Save submitted message to query history"""
        if text and text.strip() and (not self.prompt_history or self.prompt_history[-1] != text):
            self.prompt_history.append(text)
            if len(self.prompt_history) > self.MAX_PROMPT_HISTORY:
                self.prompt_history = self.prompt_history[-self.MAX_PROMPT_HISTORY :]
            self.save_prompt_history()
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

    async def _on_key(self, event: events.Key) -> None:
        if event.key in KEY_PASTE:
            if await self.try_paste_clipboard_image():
                event.prevent_default()
                event.stop()
                return

        if event.key in KEY_DETACH and self.clipboard_attachments:
            self.clear_clipboard_attachments()
            event.prevent_default()
            event.stop()
            return
        # Atomic deletion of pasted block via Backspace/Delete
        if event.key in ("backspace", "delete"):
            if self._handle_tag_deletion(event.key):
                event.prevent_default()
                event.stop()
                return

        # Global Exit shortcut: Ctrl+C / Ctrl+Q (and layout aliases)
        if event.key in KEY_QUIT:
            event.prevent_default()
            event.stop()
            self.app.exit()
            return

        # Cancel active suggestions popup or agent generation via Escape
        if event.key == "escape":
            try:
                from widgets.command_suggestions import CommandSuggestions

                suggestions = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
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

                suggestions = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
                if suggestions.display and suggestions.highlighted is not None:
                    if suggestions.mode == "command":
                        if suggestions.highlighted < len(suggestions.current_matched):
                            chosen_cmd = suggestions.current_matched[suggestions.highlighted]
                            self.apply_suggestion(chosen_cmd, suggestions.at_start_idx)
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
        if event.key in KEY_TOGGLE_ROLE:
            event.prevent_default()
            event.stop()
            if hasattr(self.app, "action_toggle_role"):
                self.app.action_toggle_role()
            return

        # Handle arrow navigation in suggestions menu
        try:
            from widgets.command_suggestions import CommandSuggestions

            suggestions = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
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

                suggestions = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
                if suggestions.display and suggestions.highlighted is not None:
                    if suggestions.mode == "command":
                        if suggestions.highlighted < len(suggestions.current_matched):
                            chosen_cmd = suggestions.current_matched[suggestions.highlighted]
                            self.apply_suggestion(chosen_cmd, suggestions.at_start_idx)
                            suggestions.display = False
                            if hasattr(suggestions, "_set_display") and callable(suggestions._set_display):
                                suggestions._set_display(False)
                            event.prevent_default()
                            event.stop()
                            return
                    elif suggestions.mode == "file":
                        if suggestions.highlighted < len(suggestions.current_matched):
                            chosen_file = suggestions.current_matched[suggestions.highlighted]
                            self.apply_file_suggestion(chosen_file, suggestions.at_start_idx)
                            suggestions.display = False
                            if hasattr(suggestions, "_set_display") and callable(suggestions._set_display):
                                suggestions._set_display(False)
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

                suggestions = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
                suggestions.display = False
                if hasattr(suggestions, "_set_display") and callable(suggestions._set_display):
                    suggestions._set_display(False)
            except Exception:
                pass

            text = self.get_full_text()
            atts = list(self.clipboard_attachments)
            self.clipboard_attachments.clear()
            self.update_attachment_bar()
            self.pasted_texts.clear()
            self.add_to_history(text)
            self.load_text("")
            self.post_message(self.Submitted(text, attachments=atts))
        elif event.key in KEY_NEWLINE:
            event.prevent_default()
            event.stop()
            self.insert("\n")
