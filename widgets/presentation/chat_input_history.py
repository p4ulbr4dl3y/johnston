import asyncio
from typing import TYPE_CHECKING

from core.infrastructure.platform import paths as config
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json

if TYPE_CHECKING:
    from widgets.chat_input import ChatInput


def load_prompt_history(max_history: int) -> list[str]:
    """Load global prompt history from disk"""
    data = read_json(config.PROMPT_HISTORY_FILE, default=[])
    if isinstance(data, list):
        return [str(item) for item in data][-max_history:]
    return []


def save_prompt_history_to_disk(history: list[str], max_history: int) -> None:
    try:
        atomic_write_json(config.PROMPT_HISTORY_FILE, history[-max_history:], indent=2)
    except Exception:
        pass


def save_prompt_history(widget: "ChatInput") -> None:
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
                    await asyncio.to_thread(save_prompt_history_to_disk, to_save, widget.MAX_PROMPT_HISTORY)

            widget._save_task = loop.create_task(_do_save())
    except RuntimeError:
        save_prompt_history_to_disk(history_copy, widget.MAX_PROMPT_HISTORY)


def add_to_history(widget: "ChatInput", text: str) -> None:
    """Save submitted message to query history"""
    if text and text.strip() and (not widget.prompt_history or widget.prompt_history[-1] != text):
        widget.prompt_history.append(text)
        if len(widget.prompt_history) > widget.MAX_PROMPT_HISTORY:
            widget.prompt_history = widget.prompt_history[-widget.MAX_PROMPT_HISTORY :]
        widget.save_prompt_history()
    widget.prompt_history_index = len(widget.prompt_history)
    widget.prompt_draft = ""


def handle_history_navigation(widget: "ChatInput", key: str) -> bool:
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
