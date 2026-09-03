import asyncio
import os
import re
import urllib.parse

from textual import events
from textual.message import Message
from textual.widgets import TextArea

from core.infrastructure.config.settings import get_settings
from core.infrastructure.platform import paths as config
from core.infrastructure.platform.paths import IMAGE_EXTENSIONS
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json
from widgets.presentation.screens.constants import COMMAND_SUGGESTIONS, STATUS_FOOTER
from widgets.utils.key_aliases import (
    KEY_CUT,
    KEY_DETACH,
    KEY_NEWLINE,
    KEY_PASTE,
    KEY_QUIT,
    KEY_SCROLL_BOTTOM,
    KEY_SCROLL_DOWN,
    KEY_SCROLL_TOP,
    KEY_SCROLL_UP,
    KEY_TOGGLE_MODE,
    KEY_TOGGLE_ROLE,
)
from widgets.utils.responsive import BREAKPOINT_BANNER, BREAKPOINT_COMPACT, resolve_width

MOUSE_ARTIFACT_REGEX = re.compile(r"(?:M|\[)?<[0-9]{1,3};[0-9]+;[0-9]+[Mm]")


class ClipboardAttachment:
    """Represents a clipboard image attachment"""

    def __init__(self, path: str):
        self.path = path


DEFAULT_PLACEHOLDER = "Type a message (? help, / cmds)..."
COMPACT_PLACEHOLDER = "Type message (? help, / cmds)..."
NARROW_PLACEHOLDER = "Type a message..."
FORK_PLACEHOLDER = "Type a message to fork & continue..."

DEFAULT_SHELL_PLACEHOLDER = "! git status, pytest (esc to exit)..."
COMPACT_SHELL_PLACEHOLDER = "! command (esc to exit)..."
NARROW_SHELL_PLACEHOLDER = "! (esc to exit)..."


def get_placeholder_for_width(width: int) -> str:
    """Return responsive placeholder text based on width."""
    if width < BREAKPOINT_BANNER:
        return NARROW_PLACEHOLDER
    if width < BREAKPOINT_COMPACT:
        return COMPACT_PLACEHOLDER
    return DEFAULT_PLACEHOLDER


def get_shell_placeholder_for_width(width: int) -> str:
    """Return responsive shell mode placeholder text based on width."""
    if width < BREAKPOINT_BANNER:
        return NARROW_SHELL_PLACEHOLDER
    if width < BREAKPOINT_COMPACT:
        return COMPACT_SHELL_PLACEHOLDER
    return DEFAULT_SHELL_PLACEHOLDER


class ChatInput(TextArea):
    """Input field with reactive suggestions on character typing"""

    class Submitted(Message):
        """Text submission event"""

        def __init__(self, value: str, attachments: list = None) -> None:
            super().__init__()
            self.value = value
            self.attachments = list(attachments or [])

    @property
    def PASTE_LINE_THRESHOLD(self) -> int:
        return get_settings().ui.paste_line_threshold

    @property
    def MAX_PROMPT_HISTORY(self) -> int:
        """Max entries retained in prompt history (configurable via ui.max_prompt_history)."""
        if hasattr(self, "_max_prompt_history") and self._max_prompt_history is not None:
            return self._max_prompt_history
        return get_settings().ui.max_prompt_history

    @MAX_PROMPT_HISTORY.setter
    def MAX_PROMPT_HISTORY(self, value: int) -> None:
        self._max_prompt_history = value

    def __init__(self, **kwargs):
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("placeholder", DEFAULT_PLACEHOLDER)
        super().__init__(**kwargs)
        self.pasted_texts: dict[str, str] = {}
        self.clipboard_attachments: list = []
        self.prompt_history: list[str] = self.load_prompt_history()
        self.prompt_history_index: int = len(self.prompt_history)
        self.prompt_draft: str = ""
        self.is_shell_mode: bool = False
        self._suggestions_active: bool = False

    def set_shell_mode(self, enabled: bool) -> None:
        """Toggle shell mode state and update placeholder / styling."""
        if self.is_shell_mode == enabled:
            return
        self.is_shell_mode = enabled
        if enabled:
            self.add_class("shell-mode")
        else:
            self.remove_class("shell-mode")
        self.update_placeholder()

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
        self._pending_prompt_history = history_copy
        try:
            loop = asyncio.get_running_loop()
            if getattr(self, "_save_task", None) is None or self._save_task.done():
                async def _do_save():
                    while getattr(self, "_pending_prompt_history", None) is not None:
                        to_save = self._pending_prompt_history
                        self._pending_prompt_history = None
                        await asyncio.to_thread(self._save_prompt_history_to_disk, to_save)

                self._save_task = loop.create_task(_do_save())
        except RuntimeError:
            self._save_prompt_history_to_disk(history_copy)

    def update_placeholder(self, width: int | None = None) -> None:
        """Update placeholder responsively unless a custom placeholder is set."""
        if self.is_shell_mode:
            w = width if width is not None else resolve_width(self)
            self.placeholder = get_shell_placeholder_for_width(w)
            return
        try:
            if getattr(self.app, "is_read_only", False):
                self.placeholder = FORK_PLACEHOLDER
                return
        except Exception:
            pass
        if self.placeholder not in (
            DEFAULT_PLACEHOLDER,
            COMPACT_PLACEHOLDER,
            NARROW_PLACEHOLDER,
            DEFAULT_SHELL_PLACEHOLDER,
            COMPACT_SHELL_PLACEHOLDER,
            NARROW_SHELL_PLACEHOLDER,
            "",
        ):
            return
        w = width if width is not None else resolve_width(self)
        self.placeholder = get_placeholder_for_width(w)

    def on_mount(self) -> None:
        self.focus()
        self.update_height()
        self.update_placeholder()

    def on_resize(self, event: events.Resize) -> None:
        self.update_placeholder(event.size.width)

    def on_unmount(self) -> None:
        if getattr(self, "_save_task", None) is not None and not self._save_task.done():
            self._save_task.cancel()
        if getattr(self, "_pending_prompt_history", None) is not None:
            self._save_prompt_history_to_disk(self._pending_prompt_history)
            self._pending_prompt_history = None

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
        """Dynamic height calculation from 2/3 to 6 lines, taking wrapped lines into account"""
        raw_lines = len(self.text.split("\n"))
        wrapped_lines = getattr(self.wrapped_document, "height", 1) if hasattr(self, "wrapped_document") else 1
        lines = max(raw_lines, wrapped_lines)
        max_lines = get_settings().ui.max_chat_input_lines
        has_attachments = bool(getattr(self, "clipboard_attachments", None))

        pad_lines = 1 if has_attachments else 2
        min_h = 2 if has_attachments else 3
        target_height = max(min_h, min(lines + pad_lines, max_lines))

        expected_padding = (0, 1, 1, 1) if has_attachments else (1, 1, 1, 1)
        if self.styles.padding != expected_padding:
            self.styles.padding = expected_padding

        h = self.styles.height
        if h is None or h.value != target_height or str(getattr(h, "unit", "")) != "Unit.CELLS":
            self.styles.height = target_height

        try:
            if self.is_mounted and self.app:
                from widgets.command_suggestions import CommandSuggestions

                att_offset = 2 if has_attachments else 0
                footer_offset = 3
                margin_b = target_height + footer_offset + att_offset - 1

                sugg = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
                new_margin = (0, 0, margin_b, 0)
                if sugg.styles.margin != new_margin:
                    sugg.styles.margin = new_margin
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

    def _has_suggestion_trigger(self) -> bool:
        """Return True when the cursor line carries an active /command or @file trigger.

        Mirrors the trigger conditions in CommandSuggestions.update_query: a "/"
        (outside shell mode) or "@" at line start or after whitespace, with no
        spaces/newlines in the query part up to the cursor.
        """
        row, col = self.cursor_location
        check_text = self.document.get_line(row)[:col]
        if not self.is_shell_mode:
            slash_idx = check_text.rfind("/")
            if slash_idx != -1 and (slash_idx == 0 or check_text[slash_idx - 1] in " \t\n"):
                query_part = check_text[slash_idx:]
                if " " not in query_part and "\n" not in query_part:
                    return True
        at_idx = check_text.rfind("@")
        if at_idx != -1 and (at_idx == 0 or check_text[at_idx - 1] in " \t\n"):
            query_part = check_text[at_idx + 1 :]
            if " " not in query_part and "\n" not in query_part:
                return True
        return False

    def _schedule_suggestions_update(self) -> None:
        """Schedule suggestion refresh off the event loop when mounted.

        Gated: the task is only spawned when the cursor line has an active "/" or
        "@" trigger, or when a previously-open suggestions list needs clearing
        after its trigger disappeared. Input changes without either never spawn a
        task, avoiding the per-key query/update overhead entirely.
        """
        if not getattr(self, "is_mounted", False):
            return
        has_trigger = self._has_suggestion_trigger()
        if not has_trigger and not getattr(self, "_suggestions_active", False):
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.update_suggestions())
        except RuntimeError:
            return
        self._suggestions_active = has_trigger

    def _on_input_change(self) -> None:
        """Called on any input text change"""
        self.sanitize_mouse_artifacts()
        self.update_height()
        self._schedule_suggestions_update()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._on_input_change()

    async def _on_mouse_up(self, event: events.MouseUp) -> None:
        await super()._on_mouse_up(event)
        selected = self.selected_text
        if selected and selected.strip():
            if hasattr(self.app, "copy_to_clipboard"):
                self.app.copy_to_clipboard(selected)
            self.selection = self.selection.__class__.cursor(self.cursor_location)

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

    def _accept_active_suggestion(self) -> bool:
        """Apply active suggestion if suggestion menu is visible."""
        try:
            from widgets.command_suggestions import CommandSuggestions

            suggestions = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
            if suggestions.display and suggestions.highlighted is not None:
                if suggestions.highlighted < len(suggestions.current_matched):
                    chosen = suggestions.current_matched[suggestions.highlighted]
                    if suggestions.mode == "command":
                        self.apply_suggestion(chosen, suggestions.at_start_idx)
                    elif suggestions.mode == "file":
                        self.apply_file_suggestion(chosen, suggestions.at_start_idx)
                    suggestions.display = False
                    if hasattr(suggestions, "_set_display") and callable(suggestions._set_display):
                        suggestions._set_display(False)
                    return True
        except Exception:
            pass
        return False

    def _handle_chat_scroll_keys(self, key: str) -> bool:
        """Handle page up/down and top/bottom chat scroll keys."""
        if (
            key not in KEY_SCROLL_UP
            and key not in KEY_SCROLL_DOWN
            and key not in KEY_SCROLL_TOP
            and key not in KEY_SCROLL_BOTTOM
        ):
            return False
        try:
            from widgets.presentation.widgets.chat_container import ChatView

            chat_view = self.app.query_one(ChatView)
            if key in KEY_SCROLL_UP:
                chat_view.scroll_up_page()
            elif key in KEY_SCROLL_DOWN:
                chat_view.scroll_down_page()
            elif key in KEY_SCROLL_TOP:
                chat_view.scroll_to_top()
            elif key in KEY_SCROLL_BOTTOM:
                chat_view.scroll_to_bottom()
            return True
        except Exception:
            return False

    def _handle_history_navigation(self, key: str) -> bool:
        """Navigate prompt history when cursor is at the top/bottom boundary."""
        lines = self.text.split("\n")
        if key == "up" and self.cursor_location[0] == 0:
            if not self.prompt_history:
                return False
            if self.prompt_history_index == len(self.prompt_history):
                self.prompt_draft = self.text

            if self.prompt_history_index == 0:
                self.prompt_history_index = len(self.prompt_history)
                self.load_text(self.prompt_draft)
            else:
                self.prompt_history_index -= 1
                self.load_text(self.prompt_history[self.prompt_history_index])

            new_lines = self.text.split("\n")
            self.move_cursor((len(new_lines) - 1, len(new_lines[-1])))
            return True

        if key == "down" and self.cursor_location[0] == len(lines) - 1:
            if not self.prompt_history:
                return False
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

            new_lines = self.text.split("\n")
            self.move_cursor((len(new_lines) - 1, len(new_lines[-1])))
            return True

        return False

    async def _on_key(self, event: events.Key) -> None:
        if event.key in KEY_PASTE:
            if await self.try_paste_clipboard_image():
                event.prevent_default()
                event.stop()
                return

        if event.key in KEY_DETACH and self.clipboard_attachments:
            self.remove_clipboard_attachment(self.clipboard_attachments[-1])
            event.prevent_default()
            event.stop()
            return
        # Atomic deletion of pasted block via Backspace/Delete
        if event.key in ("backspace", "delete"):
            if self._handle_tag_deletion(event.key):
                event.prevent_default()
                event.stop()
                return

        # Cut selected text (Ctrl+X / Cmd+X)
        if event.key in KEY_CUT and self.selected_text:
            self.action_cut()
            event.prevent_default()
            event.stop()
            return

        # Main chat history scrolling via keyboard
        if self._handle_chat_scroll_keys(event.key):
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

        # Tab press: accept suggestion if open, otherwise toggle agent role
        if event.key in KEY_TOGGLE_ROLE:
            if self._accept_active_suggestion():
                event.prevent_default()
                event.stop()
                return
            event.prevent_default()
            event.stop()
            if hasattr(self.app, "action_toggle_role"):
                self.app.action_toggle_role()
            return

        # Shift+Tab press to toggle execution mode (review / edits / yolo)
        if event.key in KEY_TOGGLE_MODE:
            event.prevent_default()
            event.stop()
            if hasattr(self.app, "action_toggle_mode"):
                self.app.action_toggle_mode()
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

        # Open Help modal when typing ? into empty input
        if not self.is_shell_mode and not self.text:
            if getattr(event, "character", "") == "?" or event.key in ("?", "question_mark"):
                if self.app and hasattr(self.app, "push_screen"):
                    from widgets.presentation.screens.help import HelpScreen

                    self.app.push_screen(HelpScreen())
                event.prevent_default()
                event.stop()
                return

        # Toggle Shell mode when typing ! into empty input
        if not self.is_shell_mode and not self.text:
            if getattr(event, "character", "") == "!" or event.key in ("!", "exclamation_mark"):
                self.set_shell_mode(True)
                event.prevent_default()
                event.stop()
                return

        # Exit shell mode on backspace/delete/escape when input is empty
        if self.is_shell_mode and not self.text:
            if event.key in ("backspace", "delete", "escape"):
                self.set_shell_mode(False)
                event.prevent_default()
                event.stop()
                return

        # Looped navigation through query history
        if self._handle_history_navigation(event.key):
            event.prevent_default()
            event.stop()
            return

        if event.key == "enter":
            # Select suggestion if suggestion menu is open
            if self._accept_active_suggestion():
                event.prevent_default()
                event.stop()
                return

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
            was_shell = self.is_shell_mode
            if self.is_shell_mode:
                self.set_shell_mode(False)
            if was_shell and text and not text.startswith("!"):
                text = f"!{text}"

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
