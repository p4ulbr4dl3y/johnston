"""Backward-compatible re-exports for chat input history."""
from widgets.presentation.widgets.chat_input_history import (
    ChatInputHistoryMixin,
    add_to_history,
    handle_history_navigation,
    load_prompt_history,
    save_prompt_history,
    save_prompt_history_to_disk,
)

__all__ = [
    "ChatInputHistoryMixin",
    "add_to_history",
    "handle_history_navigation",
    "load_prompt_history",
    "save_prompt_history",
    "save_prompt_history_to_disk",
]
