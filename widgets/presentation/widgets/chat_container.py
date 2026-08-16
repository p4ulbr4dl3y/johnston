import asyncio

from textual.containers import VerticalScroll

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
            while not self.is_attached and (loop.time() - t0 < timeout):
                await asyncio.sleep(0.005)
        except Exception:
            pass

    async def _mount_and_scroll(self, widget, should_scroll: bool = True, animate: bool = True):
        self.clear_welcome()
        if not self.is_attached:
            await self._wait_until_attached()
        await self.mount(widget)
        if should_scroll:
            self.call_after_refresh(self.scroll_end, animate=animate)
        return widget

    async def add_user_message(self, text: str, animate: bool = True, attachments: list = None) -> UserMessage:
        if attachments:
            att_count = len(attachments)
            img_s = "s" if att_count > 1 else ""
            display_text = f"{text}\n└─ {att_count} image{img_s} attached"
        else:
            display_text = text

        msg = UserMessage(display_text or "", markup=False)
        return await self._mount_and_scroll(msg, should_scroll=not self._is_loading_session, animate=animate)

    async def add_bot_message(self, animate: bool = True) -> BotMessage:
        msg = BotMessage()
        should_scroll = not self._is_loading_session and (not animate or self.is_at_bottom())
        return await self._mount_and_scroll(msg, should_scroll=should_scroll, animate=animate)

    async def add_thinking_widget(self, thinking_text: str = "Thinking...", animate: bool = True) -> ThinkingWidget:
        widget = ThinkingWidget(thinking_text)
        should_scroll = not self._is_loading_session and (not animate or self.is_at_bottom())
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate)

    async def add_tool_call(
        self,
        tool_type: str,
        target: str,
        result_text: str = "",
        args: dict = None,
        animate: bool = True,
        status: str = None,
        returncode: int = None,
    ) -> ToolCallWidget:
        last_child = None
        for child in reversed(self.children):
            if isinstance(child, BotMessage) and not child.content.strip():
                continue
            last_child = child
            break
        is_seq = bool(last_child and isinstance(last_child, ToolCallWidget))
        widget = ToolCallWidget(
            tool_type,
            target,
            result_text=result_text,
            is_sequential=is_seq,
            args=args,
            status=status,
            returncode=returncode,
        )
        should_scroll = not self._is_loading_session and (not animate or self.is_at_bottom())
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate)

    async def add_event_divider(self, text: str = "Session Compacted", animate: bool = True) -> EventDivider:
        widget = EventDivider(text)
        should_scroll = not self._is_loading_session and (not animate or self.is_at_bottom())
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

        if not expandables:
            return

        mode_clean = (mode or "all").lower().strip()

        if mode_clean in ("collapse", "collapse_all", "close"):
            for w in expandables:
                if getattr(w, "is_expanded", False):
                    w.toggle_expanded()
        elif mode_clean in ("expand_all", "expand"):
            for w in expandables:
                if not getattr(w, "is_expanded", False):
                    w.toggle_expanded()
        elif mode_clean in ("last", "focused", "focus"):
            focused = self.app.focused if hasattr(self, "app") and self.app else None
            target_widget = None
            if focused and (
                isinstance(focused, (ThinkingWidget, ToolCallWidget))
                and getattr(focused, "is_expandable", lambda: False)()
            ):
                target_widget = focused
            else:
                target_widget = expandables[-1]
            if target_widget:
                target_widget.toggle_expanded()
        else:
            any_collapsed = any(not getattr(w, "is_expanded", False) for w in expandables)
            for w in expandables:
                if any_collapsed:
                    if not getattr(w, "is_expanded", False):
                        w.toggle_expanded()
                else:
                    if getattr(w, "is_expanded", False):
                        w.toggle_expanded()
