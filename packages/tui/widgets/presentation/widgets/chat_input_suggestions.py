import asyncio
from typing import Any


class ChatInputSuggestionsMixin:
    """Reactive slash command and file suggestions for ChatInput."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._suggestions_active: bool = False

    async def update_suggestions(self) -> None:
        """Update slash command and file suggestions list"""
        try:
            if self.is_mounted and self.app:
                from widgets.command_suggestions import CommandSuggestions
                from widgets.presentation.screens.constants import COMMAND_SUGGESTIONS

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

    def _has_suggestion_trigger(self) -> bool:
        """Return True when the cursor line carries an active /command or @file trigger."""
        row, col = self.cursor_location
        check_text = self.document.get_line(row)[:col]
        if not getattr(self, "is_shell_mode", False):
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
        """Schedule suggestion refresh off the event loop when mounted."""
        if not getattr(self, "is_mounted", False):
            return
        has_trigger = self._has_suggestion_trigger()
        if not has_trigger and not getattr(self, "_suggestions_active", False):
            return
        try:
            import sys

            chat_mod = sys.modules.get("widgets.chat_input")
            _asyncio = getattr(chat_mod, "asyncio", asyncio) if chat_mod else asyncio
            loop = _asyncio.get_running_loop()
            loop.create_task(self.update_suggestions())
        except RuntimeError:
            return
        self._suggestions_active = has_trigger

    def _accept_active_suggestion(self) -> bool:
        """Apply active suggestion if suggestion menu is visible."""
        try:
            from widgets.command_suggestions import CommandSuggestions
            from widgets.presentation.screens.constants import COMMAND_SUGGESTIONS

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


__all__ = [
    "ChatInputSuggestionsMixin",
]
