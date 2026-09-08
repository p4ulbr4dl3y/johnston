import asyncio

from textual import events
from textual.message import Message
from textual.widgets import TextArea

from johnston_core.infrastructure.config.settings import get_settings
from johnston_core.infrastructure.platform import paths as config
from johnston_core.infrastructure.platform.platform_utils import atomic_write_json, read_json
from johnston_tui.presentation.chat_input_placeholders import (
    COMPACT_PLACEHOLDER,
    COMPACT_SHELL_PLACEHOLDER,
    DEFAULT_PLACEHOLDER,
    DEFAULT_SHELL_PLACEHOLDER,
    FORK_PLACEHOLDER,
    NARROW_PLACEHOLDER,
    NARROW_SHELL_PLACEHOLDER,
    get_placeholder_for_width,
    get_shell_placeholder_for_width,
)
from johnston_tui.presentation.widgets.chat_input_history import ChatInputHistoryMixin
from johnston_tui.presentation.widgets.chat_input_paste import (
    ChatInputPasteMixin,
    ClipboardAttachment,
)
from johnston_tui.presentation.widgets.chat_input_suggestions import ChatInputSuggestionsMixin
from johnston_tui.utils.key_aliases import (
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
from johnston_tui.utils.responsive import resolve_width


class ChatInput(ChatInputHistoryMixin, ChatInputSuggestionsMixin, ChatInputPasteMixin, TextArea):
    """Input field with reactive suggestions on character typing"""

    class Submitted(Message):
        """Text submission event"""

        def __init__(self, value: str, attachments: list = None) -> None:
            super().__init__()
            self.value = value
            self.attachments = list(attachments or [])

    def __init__(self, **kwargs):
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("placeholder", DEFAULT_PLACEHOLDER)
        super().__init__(**kwargs)
        self.is_shell_mode: bool = False

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

    def load_text(self, text: str) -> None:
        if text is None:
            text = ""
        if not text:
            self.pasted_texts.clear()
        super().load_text(text)
        self._on_input_change()

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
                from johnston_tui.command_suggestions import CommandSuggestions
                from johnston_tui.presentation.screens.constants import COMMAND_SUGGESTIONS

                att_offset = 2 if has_attachments else 0
                footer_offset = 3
                margin_b = target_height + footer_offset + att_offset - 1

                sugg = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
                new_margin = (0, 0, margin_b, 0)
                if sugg.styles.margin != new_margin:
                    sugg.styles.margin = new_margin
        except Exception:
            pass

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
            from johnston_tui.presentation.widgets.chat_container import ChatView

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
            if self.app:
                self.app.is_app_active = False
                for w in getattr(self.app, "workers", []):
                    if getattr(w, "is_running", False):
                        w.cancel()
                self.app.exit()
            return

        # Cancel active suggestions popup or agent generation via Escape
        if event.key == "escape":
            try:
                from johnston_tui.command_suggestions import CommandSuggestions
                from johnston_tui.presentation.screens.constants import COMMAND_SUGGESTIONS

                suggestions = self.app.query_one(COMMAND_SUGGESTIONS, CommandSuggestions)
                if suggestions.display:
                    suggestions.display = False
                    event.prevent_default()
                    event.stop()
                    return
            except Exception:
                pass

            # Stop generation: Textual workers and the registered compaction task
            # (if any; /compact runs in a plain asyncio task, so it is tracked
            # separately on the app). Subagents and background tasks run in the
            # background and are NOT cancelled via Esc in chat (only explicitly
            # via ctrl+k in their console/modal screens).
            active_workers = [w for w in self.app.workers if w.is_running]
            for w in active_workers:
                w.cancel()
            compact_cancelled = False
            compact_task = getattr(self.app, "_compact_task", None)
            if compact_task is not None and not compact_task.done():
                compact_task.cancel()
                compact_cancelled = True
            if active_workers or compact_cancelled:
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
            from johnston_tui.command_suggestions import CommandSuggestions
            from johnston_tui.presentation.screens.constants import COMMAND_SUGGESTIONS

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
                    from johnston_tui.presentation.screens.help import HelpScreen

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
                from johnston_tui.command_suggestions import CommandSuggestions
                from johnston_tui.presentation.screens.constants import COMMAND_SUGGESTIONS

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


__all__ = [
    "ChatInput",
    "ChatInputHistoryMixin",
    "ChatInputPasteMixin",
    "ChatInputSuggestionsMixin",
    "ClipboardAttachment",
    "COMPACT_PLACEHOLDER",
    "COMPACT_SHELL_PLACEHOLDER",
    "DEFAULT_PLACEHOLDER",
    "DEFAULT_SHELL_PLACEHOLDER",
    "FORK_PLACEHOLDER",
    "NARROW_PLACEHOLDER",
    "NARROW_SHELL_PLACEHOLDER",
    "get_placeholder_for_width",
    "get_shell_placeholder_for_width",
    "KEY_QUIT",
    "asyncio",
    "config",
    "read_json",
    "atomic_write_json",
]
