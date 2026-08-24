import asyncio

from textual import events
from textual.containers import VerticalScroll

from core.infrastructure.mcp import mcp_tool_is_known
from widgets.chat_toolcall import ToolCallWidget
from widgets.presentation.widgets.chat_markdown import _apply_chat_markdown_patches
from widgets.presentation.widgets.chat_messages import BotMessage, EventDivider, ThinkingWidget, UserMessage
from widgets.presentation.widgets.chat_welcome import WelcomeWidget


class ChatView(VerticalScroll):
    """Scrollable chat stream"""

    can_focus = False

    def __init__(self, *args, show_welcome: bool = True, **kwargs):
        _apply_chat_markdown_patches()
        super().__init__(*args, **kwargs)
        self.show_welcome = show_welcome
        self._is_loading_session: bool = False
        # Bottom-follow intent. Cleared by an upward wheel tick, restored by
        # scrolling back to the bottom or by sending a new message.
        self._auto_follow: bool = True
        self.auto_expand_all: bool = False

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        # Pause bottom-follow as soon as the view has somewhere to scroll up;
        # keeps a single wheel tick from being undone by the next stream flush.
        if self.max_scroll_y > 0:
            self._auto_follow = False

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        # The framework's own scroll for this tick runs after this handler;
        # defer the check so it sees the post-tick position.
        self.call_after_refresh(self._resume_follow_if_at_bottom)

    def _resume_follow_if_at_bottom(self) -> None:
        if self.is_at_bottom():
            self._auto_follow = True

    def is_at_bottom(self, threshold: int = 3) -> bool:
        """Returns True if scroll position is at or near the bottom of the container."""
        return (self.max_scroll_y - self.scroll_y) <= threshold

    def on_mount(self) -> None:
        self.check_welcome()

    def clear_welcome(self) -> None:
        for w in self.query(WelcomeWidget):
            w.remove()

    def check_welcome(self) -> None:
        if not getattr(self, "show_welcome", True):
            self.clear_welcome()
            return
        msg_children = [c for c in self.children if not isinstance(c, WelcomeWidget)]
        welcome = list(self.query(WelcomeWidget))
        if not msg_children:
            if not welcome:
                self.mount(WelcomeWidget())
        else:
            for w in welcome:
                w.remove()

    async def _wait_until_attached(self, timeout: float = 0.5) -> None:
        try:
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            # Detached barely ever happens on the hot path; when it does, wait
            # with a coarse increment so we don't run 100 empty wakeups at 5ms.
            while not self.is_attached and (loop.time() - t0 < timeout):
                await asyncio.sleep(0.02)
        except Exception:
            pass

    async def _mount_and_scroll(
        self,
        widget,
        should_scroll: bool = True,
        animate: bool = False,
    ):
        """Mount ``widget`` and optionally snap to the bottom.

        Auto-follow scrolls are always instant: animated scrolls get superseded
        by the next debounced stream flush (~50ms) and leave the tail jittering.
        """
        self.clear_welcome()
        if not self.is_attached:
            await self._wait_until_attached()
        await self.mount(widget)
        if should_scroll:
            self.call_after_refresh(self.scroll_end, animate=animate)
        return widget

    async def add_user_message(
        self,
        text: str,
        animate: bool = False,
        attachments: list = None,
        attachments_count: int = 0,
    ) -> UserMessage:
        att_count = attachments_count or (len(attachments) if attachments else 0)
        if att_count > 0:
            img_s = "s" if att_count > 1 else ""
            att_text = f"└─ {att_count} image{img_s} attached"
            msg = UserMessage(text or "", attachment_text=att_text, markup=False)
        else:
            msg = UserMessage(text or "", markup=False)

        # Sending a message returns attention to the live tail.
        self._auto_follow = True
        return await self._mount_and_scroll(msg, should_scroll=not self._is_loading_session, animate=animate)

    async def add_bot_message(self, animate: bool = False) -> BotMessage:
        msg = BotMessage()
        should_scroll = not self._is_loading_session and self.is_at_bottom()
        return await self._mount_and_scroll(msg, should_scroll=should_scroll, animate=animate)

    async def add_thinking_widget(
        self,
        thinking_text: str = "Thinking...",
        animate: bool = False,
    ) -> ThinkingWidget:
        widget = ThinkingWidget(thinking_text)
        if self.auto_expand_all and widget.is_expandable():
            widget.is_expanded = True
        should_scroll = not self._is_loading_session and self.is_at_bottom()
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate)

    async def add_tool_call(
        self,
        tool_type: str,
        target: str,
        result_text: str = "",
        args: dict = None,
        animate: bool = False,
        status: str = None,
        returncode: int = None,
    ) -> ToolCallWidget:
        last_child = None
        for child in reversed(self.children):
            if isinstance(child, BotMessage):
                c_str = (
                    child._join_stream_content()
                    if hasattr(child, "_join_stream_content") and child._stream_parts
                    else getattr(child, "content", "")
                )
                if not (c_str or "").strip():
                    continue
            last_child = child
            break
        is_seq = bool(last_child and isinstance(last_child, ToolCallWidget))
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
        )
        if self.auto_expand_all and widget.is_expandable():
            widget.is_expanded = True
        should_scroll = not self._is_loading_session and self.is_at_bottom()
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate)

    async def add_event_divider(self, text: str = "Session Compacted", animate: bool = False) -> EventDivider:
        widget = EventDivider(text)
        should_scroll = not self._is_loading_session and self.is_at_bottom()
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate)

    def get_user_messages(self) -> list[tuple[int, str]]:
        result = []
        for idx, child in enumerate(self.children):
            if isinstance(child, UserMessage):
                result.append((idx, child.raw_text))
        return result

    def rollback_to(self, target_index: int) -> None:
        children = list(self.children)
        start_idx = max(0, target_index + 1)
        for child in children[start_idx:]:
            child.remove()
        self.check_welcome()

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
