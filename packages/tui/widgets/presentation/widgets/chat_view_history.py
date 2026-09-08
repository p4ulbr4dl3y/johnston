"""ChatView history facade — delegates to focused components.

Public API preserved exactly:
- ``ChatViewHistoryMixin`` (mixin class for ChatView)
- ``restore_message_item`` (async function for transcript restoration)

Internal helpers (``_resolve_restore_message_item``, ``_get_settings``) are
kept as aliases for backward compatibility with runtime injection in
``chat_container``.
"""
from typing import Any

from widgets.presentation.widgets.chat_view_pagination import ChatViewPaginationMixin
from widgets.presentation.widgets.chat_view_restore import (
    resolve_restore_message_item as _resolve_restore_message_item,
)
from widgets.presentation.widgets.chat_view_restore import (
    resolve_settings as _get_settings,
)
from widgets.presentation.widgets.chat_view_restore import (
    restore_message_item,
)
from widgets.presentation.widgets.chat_view_session_loader import ChatViewSessionLoaderMixin

__all__ = ["ChatViewHistoryMixin", "restore_message_item"]


class ChatViewHistoryMixin(ChatViewPaginationMixin, ChatViewSessionLoaderMixin):
    """Pagination, session loading, welcome widget, and message restoration for ChatView."""

    PAGINATION_THRESHOLD: int = 10

    @property
    def PAGE_SIZE(self) -> int:
        """Messages mounted per page when restoring older sessions (ui.chat_page_size)."""
        if hasattr(self, "_page_size") and self._page_size is not None:
            return self._page_size
        return _get_settings().ui.chat_page_size

    @PAGE_SIZE.setter
    def PAGE_SIZE(self, value: int) -> None:
        self._page_size = value

    def __init__(self, *args: Any, show_welcome: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.show_welcome = show_welcome

    async def restore_message(self, msg: dict, before: Any = None, task_manager: Any = None) -> Any:
        """Restore a single message item dict into this view."""
        fn = _resolve_restore_message_item()
        return await fn(self, msg, before=before, task_manager=task_manager)
