import asyncio

from textual.containers import VerticalScroll

from widgets.chat_messages import BotMessage, EventDivider, ThinkingWidget, UserMessage
from widgets.chat_tools import ToolCallWidget
from widgets.chat_welcome import WelcomeWidget


class ChatView(VerticalScroll):
    """Scrollable chat stream"""

    can_focus = False

    def __init__(self, *args, show_welcome: bool = True, **kwargs):
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
        self, tool_type: str, target: str, result_text: str = "", args: dict = None, animate: bool = True
    ) -> ToolCallWidget:
        last_child = None
        for child in reversed(self.children):
            if isinstance(child, BotMessage) and not child.content.strip():
                continue
            last_child = child
            break
        is_seq = bool(last_child and isinstance(last_child, ToolCallWidget))
        widget = ToolCallWidget(tool_type, target, result_text=result_text, is_sequential=is_seq, args=args)
        should_scroll = not self._is_loading_session and (not animate or self.is_at_bottom())
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate)

    async def add_event_divider(self, text: str = "Session Compacted", animate: bool = True) -> EventDivider:
        widget = EventDivider(text)
        should_scroll = not self._is_loading_session and (not animate or self.is_at_bottom())
        return await self._mount_and_scroll(widget, should_scroll=should_scroll, animate=animate)

    async def restore_messages(self, msgs: list, loading: bool = True) -> None:
        """Render a sequence of persisted message dicts into the chat view.

        Shared restore logic used by session resume and the subagent detail screen
        so message rendering lives in one place instead of being duplicated.
        Each msg is ``{"type": ..., ...}`` matching the shapes persisted by
        ``SessionPersistenceMixin._get_current_session_data``.
        """
        self._is_loading_session = loading
        try:
            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                try:
                    mtype = msg.get("type")
                    if mtype == "user":
                        await self.add_user_message(msg.get("text", ""), animate=False)
                    elif mtype == "bot":
                        bm = await self.add_bot_message(animate=False)
                        await bm.set_final_content(msg.get("text", ""))
                    elif mtype == "thinking":
                        tw = await self.add_thinking_widget(animate=False)
                        tw.finish_thinking(msg.get("duration", 0.0), msg.get("text", ""))
                    elif mtype == "tool":
                        await self.add_tool_call(
                            msg.get("tool_type", ""),
                            msg.get("target", ""),
                            result_text=msg.get("result_text", ""),
                            args=msg.get("args", {}),
                            animate=False,
                        )
                    elif mtype == "event_divider":
                        await self.add_event_divider(msg.get("text", "Session Compacted"), animate=False)
                    elif mtype == "status_change":
                        pass
                    if len(self.children) % 5 == 0:
                        await asyncio.sleep(0)
                except Exception:
                    continue
        finally:
            self._is_loading_session = False

    async def append_event(self, evt: dict, animate: bool = True) -> None:
        """Render a single live event dict into the chat view.

        Used by the subagent detail screen to stream live events on top of the
        restored history. Tracks streaming bot/tool/thinking state on the widget so
        subsequent deltas update the same bubble. Recognised ``evt["type"]`` values
        match the persisted shapes: ``user``, ``bot``, ``thinking``, ``tool``,
        ``event_divider``, ``status_change``.
        """
        etype = evt.get("type")
        if etype == "user":
            await self.add_user_message(evt.get("text", ""), animate=animate)
        elif etype == "thinking":
            txt = evt.get("text", "")
            thinking = self._stream_thinking if hasattr(self, "_stream_thinking") else None
            if thinking is None:
                thinking = await self.add_thinking_widget(txt, animate=animate)
                self._stream_thinking = thinking
            else:
                thinking.update_thinking(txt)
            if evt.get("duration") is not None:
                thinking.finish_thinking(evt.get("duration", 0.0), txt)
                self._stream_thinking = None
        elif etype == "tool":
            if "result_text" in evt and not evt.get("tool_type"):
                if self._stream_tool:
                    self._stream_tool.set_result(evt.get("result_text", ""))
            else:
                await self._finish_stream_bot()
                tool = await self.add_tool_call(
                    evt.get("tool_type", ""),
                    evt.get("target", ""),
                    result_text=evt.get("result_text", ""),
                    args=evt.get("args", {}),
                    animate=animate,
                )
                self._stream_tool = tool
        elif etype == "bot":
            txt = evt.get("text", "")
            if txt:
                if self._stream_bot is None:
                    self._stream_bot = await self.add_bot_message(animate=animate)
                if evt.get("final") or not animate:
                    await self._stream_bot.set_final_content(txt)
                    self._stream_bot = None
                else:
                    self._stream_bot.set_stream_content(txt)
        elif etype == "event_divider":
            await self.add_event_divider(evt.get("text", "Session Compacted"), animate=animate)
        elif etype == "status_change":
            pass

    async def _finish_stream_bot(self) -> None:
        """Finalize or drop any partially-streamed bot bubble before a tool call."""
        if self._stream_bot is not None:
            bot = self._stream_bot
            self._stream_bot = None
            if not bot.content.strip():
                try:
                    bot.remove()
                except Exception:
                    pass
            else:
                try:
                    bot.flush_pending_stream()
                    await bot.finalize_stream()
                except Exception:
                    pass

    def reset_stream_state(self) -> None:
        """Drop any partially-streamed bot/tool/thinking widgets (before starting a new stream)."""
        self._stream_bot = None
        self._stream_tool = None
        self._stream_thinking = None

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
