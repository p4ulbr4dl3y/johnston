"""Re-export shim for the chat_tools public API.

The implementation lives in focused modules under ``widgets/`` (see
``chat_diff`` and ``chat_toolcall``). This module keeps the historical
``widgets.chat_tools`` import paths working.
"""

from widgets.chat_toolcall import ToolCallWidget, ToolScrollBox
from widgets.presentation.widgets.chat_diff import DiffRenderable, format_edit_diff

__all__ = [
    "DiffRenderable",
    "ToolCallWidget",
    "ToolScrollBox",
    "format_edit_diff",
]
