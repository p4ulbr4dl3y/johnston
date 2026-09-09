from typing import Any

from textual.containers import VerticalScroll

from johnston.core.infrastructure.config.settings import get_settings
from johnston.core.infrastructure.mcp import mcp_tool_is_known
from johnston.tui.chat_toolcall import ToolCallWidget
from johnston.tui.presentation.widgets.chat_markdown import _apply_chat_markdown_patches
from johnston.tui.presentation.widgets.chat_messages import (
    BotMessage,
    ErrorMessage,
    EventDivider,
    ThinkingWidget,
    UserMessage,
)
from johnston.tui.presentation.widgets.chat_view_hints import ChatViewHintsMixin
from johnston.tui.presentation.widgets.chat_view_history import (
    ChatViewHistoryMixin,
    restore_message_item,
)
from johnston.tui.presentation.widgets.chat_view_scroll import ChatViewScrollMixin
from johnston.tui.presentation.widgets.chat_welcome import WelcomeWidget


class ChatView(ChatViewHintsMixin, ChatViewScrollMixin, ChatViewHistoryMixin, VerticalScroll):
    """Scrollable chat stream with virtualized pagination / auto-loading"""

    can_focus = False

    def __init__(self, *args: Any, show_welcome: bool = True, **kwargs: Any) -> None:
        _apply_chat_markdown_patches()
        super().__init__(*args, show_welcome=show_welcome, **kwargs)
        self.show_welcome = show_welcome
        self.auto_expand_all: bool = False

    async def add_user_message(
        self,
        text: str,
        animate: bool = False,
        attachments: list = None,
        attachments_count: int = 0,
        before: Any = None,
    ) -> UserMessage:
        self.clear_active_hints(immediate=True)
        att_count = attachments_count or (len(attachments) if attachments else 0)
        prev_child = None
        if before is not None and before in self.children:
            idx = list(self.children).index(before)
            if idx > 0:
                prev_child = list(self.children)[idx - 1]
        elif self.children:
            prev_child = self.children[-1]

        is_first = (
            len(self.children) == 0
            or prev_child is None
            or isinstance(prev_child, (EventDivider, WelcomeWidget))
        )
        if att_count > 0:
            img_s = "s" if att_count > 1 else ""
            att_text = f"└─ {att_count} image{img_s} attached"
            msg = UserMessage(text or "", attachment_text=att_text, markup=False, is_first=is_first)
        else:
            msg = UserMessage(text or "", markup=False, is_first=is_first)

        # Sending a message returns attention to the live tail.
        if before is None:
            self._auto_follow = True
        return await self._mount_and_scroll(
            msg,
            should_scroll=not self._is_loading_session if before is None else False,
            animate=animate,
            before=before,
        )

    async def add_bot_message(self, animate: bool = False, before: Any = None) -> BotMessage:
        msg = BotMessage()
        should_scroll = not self._is_loading_session and self.is_at_bottom() if before is None else False
        return await self._mount_and_scroll(msg, should_scroll=should_scroll, animate=animate, before=before)

    async def add_thinking_widget(
        self,
        thinking_text: str = "Thinking...",
        animate: bool = False,
        before: Any = None,
        is_active: bool = True,
    ) -> ThinkingWidget:
        widget = ThinkingWidget(thinking_text, is_active=is_active)
        if self.auto_expand_all and widget.is_expandable():
            widget.is_expanded = True
        should_scroll = not self._is_loading_session and self.is_at_bottom() if before is None else False
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate, before=before)

    async def add_tool_call(
        self,
        tool_type: str,
        target: str,
        result_text: str = "",
        args: dict = None,
        animate: bool = False,
        status: str = None,
        returncode: int = None,
        before: Any = None,
        subagent_session_id: str = None,
        background_task_id: str = None,
        log_path: str = None,
    ) -> ToolCallWidget:
        last_child = None
        children_to_check = self.children if before is None else [c for c in self.children if c != before]
        for child in reversed(children_to_check):
            if getattr(child, "_pruning", False):
                continue
            if isinstance(child, BotMessage):
                c_str = (
                    child.raw_text
                    if hasattr(child, "raw_text")
                    else (
                        child._join_stream_content()
                        if hasattr(child, "_join_stream_content") and child._stream_parts
                        else getattr(child, "content", "")
                    )
                )
                if not (c_str or "").strip():
                    continue
            last_child = child
            break
        is_seq = bool(
            last_child
            and isinstance(last_child, ToolCallWidget)
            and not getattr(last_child, "is_expanded", False)
        )
        # MCP tool names aren't in the builtin registry; mark the widget so the
        # header display can snake_case them (e.g. "get-file-info").
        is_mcp = mcp_tool_is_known(tool_type)
        widget = ToolCallWidget(
            tool_type,
            target,
            result_text=result_text,
            is_sequential=is_seq,
            args=args,
            status=status,
            returncode=returncode,
            is_mcp=is_mcp,
            subagent_session_id=subagent_session_id,
            background_task_id=background_task_id,
            log_path=log_path,
        )
        if self.auto_expand_all and widget.is_expandable():
            widget.is_expanded = True
        should_scroll = not self._is_loading_session and self.is_at_bottom() if before is None else False
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate, before=before)

    async def add_event_divider(
        self,
        text: str = "Session Compacted",
        animate: bool = False,
        before: Any = None,
    ) -> EventDivider:
        widget = EventDivider(text)
        should_scroll = not self._is_loading_session and self.is_at_bottom() if before is None else False
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate, before=before)

    async def add_error_message(
        self,
        text: str = "",
        animate: bool = False,
        before: Any = None,
    ) -> ErrorMessage:
        widget = ErrorMessage(text)
        should_scroll = not self._is_loading_session and self.is_at_bottom() if before is None else False
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate, before=before)

    def get_user_messages(self) -> list[tuple[int, str]]:
        result = []
        for idx, child in enumerate(self.children):
            if isinstance(child, UserMessage):
                result.append((idx, child.raw_text))
        return result

    def get_last_bot_message_text(self) -> str | None:
        """Returns the text content of the last assistant bot message, or None."""
        for child in reversed(self.children):
            if isinstance(child, BotMessage):
                content = getattr(child, "content", "")
                if content and str(content).strip():
                    return str(content)
        return None

    def toggle_expand(self, mode: str = "all") -> None:
        """
        Expands or collapses expandable widgets in ChatView.
        Modes:
        - "all" / "toggle" (default): expand all blocks if any collapsed; otherwise collapse all blocks.
        - "expand": expand all expandable widgets.
        - "collapse": collapse all expandable widgets.
        - "last" / "focus": toggle focused or last expandable widget.
        """
        expandables = []
        for child in self.children:
            if isinstance(child, ThinkingWidget) and child.is_expandable():
                expandables.append(child)
            elif isinstance(child, ToolCallWidget) and child.is_expandable():
                expandables.append(child)

        mode_clean = (mode or "all").lower().strip()
        was_at_bottom = self.is_at_bottom()

        if mode_clean in ("collapse", "collapse_all", "close"):
            self.auto_expand_all = False
            for w in expandables:
                if getattr(w, "is_expanded", False):
                    w.toggle_expanded(scroll=False)
            if was_at_bottom:
                self.call_after_refresh(lambda: self.scroll_end(animate=False))
        elif mode_clean in ("expand_all", "expand"):
            self.auto_expand_all = True
            for w in expandables:
                if not getattr(w, "is_expanded", False):
                    w.toggle_expanded(scroll=False)
            if was_at_bottom:
                self.call_after_refresh(lambda: self.scroll_end(animate=False))
        elif mode_clean in ("last", "focused", "focus"):
            focused = self.app.focused if hasattr(self, "app") and self.app else None
            target_widget = None
            if focused and (
                isinstance(focused, (ThinkingWidget, ToolCallWidget))
                and getattr(focused, "is_expandable", lambda: False)()
            ):
                target_widget = focused
            elif expandables:
                target_widget = expandables[-1]
            if target_widget:
                target_widget.toggle_expanded(scroll=True)
        else:
            if not expandables:
                self.auto_expand_all = not self.auto_expand_all
                return

            any_collapsed = any(not getattr(w, "is_expanded", False) for w in expandables)
            self.auto_expand_all = any_collapsed
            for w in expandables:
                if any_collapsed:
                    if not getattr(w, "is_expanded", False):
                        w.toggle_expanded(scroll=False)
                else:
                    if getattr(w, "is_expanded", False):
                        w.toggle_expanded(scroll=False)
            if was_at_bottom:
                self.call_after_refresh(lambda: self.scroll_end(animate=False))


__all__ = [
    "ChatView",
    "ChatViewHintsMixin",
    "ChatViewHistoryMixin",
    "ChatViewScrollMixin",
    "get_settings",
    "restore_message_item",
]
