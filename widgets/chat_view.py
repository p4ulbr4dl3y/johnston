"""Re-export shim for the chat_view public API.

The implementation lives in focused modules under ``widgets/`` (see
``chat_markdown``, ``chat_messages``, ``chat_tools``, ``chat_welcome`` and
``chat_container``). This module keeps the historical ``widgets.chat_view``
import paths working.
"""

from widgets.presentation.widgets.chat_container import ChatView
from widgets.presentation.widgets.chat_markdown import (
    CustomMarkdownFence,
    CustomMarkdownTable,
    CustomMarkdownTableContent,
    TransparentSyntax,
    _handle_markdown_task_done,
    _new_markdown_block_get_style,
    clean_markdown_for_rendering,
    safe_update_markdown,
    to_snake_case,
)
from widgets.presentation.widgets.chat_messages import BotMessage, EventDivider, ThinkingWidget, UserMessage
from widgets.presentation.widgets.chat_tools import DiffRenderable, ToolCallWidget, ToolScrollBox, format_edit_diff
from widgets.presentation.widgets.chat_welcome import WelcomeWidget

__all__ = [
    "BotMessage",
    "ChatView",
    "EventDivider",
    "CustomMarkdownFence",
    "CustomMarkdownTable",
    "CustomMarkdownTableContent",
    "DiffRenderable",
    "ThinkingWidget",
    "ToolCallWidget",
    "ToolScrollBox",
    "TransparentSyntax",
    "UserMessage",
    "WelcomeWidget",
    "_handle_markdown_task_done",
    "_new_markdown_block_get_style",
    "clean_markdown_for_rendering",
    "format_edit_diff",
    "safe_update_markdown",
    "to_snake_case",
]
