import asyncio
from typing import Any

from johnston.tui.adapters import core_bridge

# Module-level aliases used by the sys.modules fallback below; `config` mirrors
# the chat_input module namespace so runtime-injected overrides keep working.
config = core_bridge.get_config_paths()
read_json = core_bridge.read_json
atomic_write_json = core_bridge.atomic_write_json
get_settings = core_bridge.get_settings


def load_prompt_history(max_history: int) -> list[str]:
    """Load global prompt history from disk"""
    import sys

    chat_mod = sys.modules.get("johnston.tui.presentation.widgets.chat_input")
    _read_json = getattr(chat_mod, "read_json", read_json) if chat_mod else read_json
    _config = getattr(chat_mod, "config", config) if chat_mod else config
    data = _read_json(_config.PROMPT_HISTORY_FILE, default=[])
    if isinstance(data, list):
        return [str(item) for item in data][-max_history:]
    return []


def save_prompt_history_to_disk(history: list[str], max_history: int) -> None:
    import sys

    chat_mod = sys.modules.get("johnston.tui.presentation.widgets.chat_input")
    _atomic_write_json = getattr(chat_mod, "atomic_write_json", atomic_write_json) if chat_mod else atomic_write_json
    _config = getattr(chat_mod, "config", config) if chat_mod else config
    try:
        _atomic_write_json(_config.PROMPT_HISTORY_FILE, history[-max_history:], indent=2)
    except Exception:
        pass


def save_prompt_history(widget: Any) -> None:
    """Save global prompt history to disk asynchronously off the event loop."""
    history_copy = list(widget.prompt_history)
    widget._pending_prompt_history = history_copy
    try:
        loop = asyncio.get_running_loop()
        if getattr(widget, "_save_task", None) is None or widget._save_task.done():

            async def _do_save():
                while getattr(widget, "_pending_prompt_history", None) is not None:
                    to_save = widget._pending_prompt_history
                    widget._pending_prompt_history = None
                    save_fn = getattr(widget, "_save_prompt_history_to_disk", None)
                    if callable(save_fn):
                        await asyncio.to_thread(save_fn, to_save)
                    else:
                        await asyncio.to_thread(save_prompt_history_to_disk, to_save, widget.MAX_PROMPT_HISTORY)

            widget._save_task = loop.create_task(_do_save())
    except RuntimeError:
        save_fn = getattr(widget, "_save_prompt_history_to_disk", None)
        if callable(save_fn):
            save_fn(history_copy)
        else:
            save_prompt_history_to_disk(history_copy, widget.MAX_PROMPT_HISTORY)


def add_to_history(widget: Any, text: str) -> None:
    """Save submitted message to query history"""
    if text and text.strip() and (not widget.prompt_history or widget.prompt_history[-1] != text):
        widget.prompt_history.append(text)
        if len(widget.prompt_history) > widget.MAX_PROMPT_HISTORY:
            widget.prompt_history = widget.prompt_history[-widget.MAX_PROMPT_HISTORY :]
        widget.save_prompt_history()
    widget.prompt_history_index = len(widget.prompt_history)
    widget.prompt_draft = ""


def handle_history_navigation(widget: Any, key: str) -> bool:
    """Navigate prompt history when cursor is at the top/bottom boundary."""
    lines = widget.text.split("\n")
    if key == "up" and widget.cursor_location[0] == 0:
        if not widget.prompt_history:
            return False
        if widget.prompt_history_index == len(widget.prompt_history):
            widget.prompt_draft = widget.text

        if widget.prompt_history_index == 0:
            widget.prompt_history_index = len(widget.prompt_history)
            widget.load_text(widget.prompt_draft)
        else:
            widget.prompt_history_index -= 1
            widget.load_text(widget.prompt_history[widget.prompt_history_index])

        new_lines = widget.text.split("\n")
        widget.move_cursor((len(new_lines) - 1, len(new_lines[-1])))
        return True

    if key == "down" and widget.cursor_location[0] == len(lines) - 1:
        if not widget.prompt_history:
            return False
        if widget.prompt_history_index == len(widget.prompt_history):
            widget.prompt_draft = widget.text
            widget.prompt_history_index = 0
            widget.load_text(widget.prompt_history[0])
        else:
            widget.prompt_history_index += 1
            if widget.prompt_history_index == len(widget.prompt_history):
                widget.load_text(widget.prompt_draft)
            else:
                widget.load_text(widget.prompt_history[widget.prompt_history_index])

        new_lines = widget.text.split("\n")
        widget.move_cursor((len(new_lines) - 1, len(new_lines[-1])))
        return True

    return False


class ChatInputHistoryMixin:
    """Prompt history management for ChatInput (load/save/navigate)."""

    @property
    def MAX_PROMPT_HISTORY(self) -> int:
        """Max entries retained in prompt history (configurable via ui.max_prompt_history)."""
        if hasattr(self, "_max_prompt_history") and self._max_prompt_history is not None:
            return self._max_prompt_history
        import sys

        chat_mod = sys.modules.get("johnston.tui.presentation.widgets.chat_input")
        _get_settings = getattr(chat_mod, "get_settings", get_settings) if chat_mod else get_settings
        return _get_settings().ui.max_prompt_history

    @MAX_PROMPT_HISTORY.setter
    def MAX_PROMPT_HISTORY(self, value: int) -> None:
        self._max_prompt_history = value

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._max_prompt_history: int | None = None
        self._pending_prompt_history: list[str] | None = None
        self._save_task: asyncio.Task | None = None
        self.prompt_history: list[str] = self.load_prompt_history()
        self.prompt_history_index: int = len(self.prompt_history)
        self.prompt_draft: str = ""

    def load_prompt_history(self) -> list[str]:
        """Load global prompt history from disk"""
        return load_prompt_history(self.MAX_PROMPT_HISTORY)

    def _save_prompt_history_to_disk(self, history: list[str]) -> None:
        save_prompt_history_to_disk(history, self.MAX_PROMPT_HISTORY)

    def save_prompt_history(self) -> None:
        """Save global prompt history to disk asynchronously off the event loop."""
        save_prompt_history(self)

    def add_to_history(self, text: str) -> None:
        """Save submitted message to query history"""
        add_to_history(self, text)

    def _handle_history_navigation(self, key: str) -> bool:
        """Navigate prompt history when cursor is at the top/bottom boundary."""
        return handle_history_navigation(self, key)

    def on_unmount(self) -> None:
        if getattr(self, "_save_task", None) is not None and not self._save_task.done():
            self._save_task.cancel()
        if getattr(self, "_pending_prompt_history", None) is not None:
            self._save_prompt_history_to_disk(self._pending_prompt_history)
            self._pending_prompt_history = None
        super_unmount = getattr(super(), "on_unmount", None)
        if callable(super_unmount):
            super_unmount()


__all__ = [
    "ChatInputHistoryMixin",
    "add_to_history",
    "handle_history_navigation",
    "load_prompt_history",
    "save_prompt_history",
    "save_prompt_history_to_disk",
]
