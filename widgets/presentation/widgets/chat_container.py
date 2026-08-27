import asyncio
import logging
from typing import Any

from textual import events
from textual.containers import VerticalScroll

from core.domain.policies.messages import is_ui_visible_user_message
from core.infrastructure.mcp import mcp_tool_is_known
from widgets.chat_toolcall import ToolCallWidget
from widgets.presentation.widgets.chat_markdown import _apply_chat_markdown_patches
from widgets.presentation.widgets.chat_messages import BotMessage, EventDivider, ThinkingWidget, UserMessage
from widgets.presentation.widgets.chat_welcome import WelcomeWidget

logger = logging.getLogger(__name__)


async def restore_message_item(
    chat_view: "ChatView",
    msg: dict,
    before: Any = None,
    task_manager: Any = None,
) -> Any:
    """Restore a saved transcript event dict into a rendered ChatView widget."""
    if not isinstance(msg, dict):
        return None
    mtype = msg.get("type")
    kw = {"before": before} if before is not None else {}
    if mtype == "user":
        if not is_ui_visible_user_message(msg):
            return None
        text = msg.get("display_text") or msg.get("text", "")
        att_count = msg.get("attachments_count", 0)
        if not att_count and msg.get("attachments"):
            att_count = len(msg.get("attachments"))
        return await chat_view.add_user_message(
            text,
            animate=False,
            attachments_count=att_count,
            **kw,
        )
    elif mtype == "bot":
        text = msg.get("text", "")
        if not text.strip():
            return None
        bm = await chat_view.add_bot_message(animate=False, **kw)
        if hasattr(bm, "set_final_content"):
            await bm.set_final_content(text)
        return bm
    elif mtype == "thinking":
        dur = msg.get("duration", 0.0)
        txt = msg.get("text", "")
        tw = await chat_view.add_thinking_widget(animate=False, **kw)
        if hasattr(tw, "finish_thinking"):
            tw.finish_thinking(dur, txt)
        return tw
    elif mtype == "tool":
        ttype = msg.get("tool_type", "")
        target = msg.get("target", "")
        rtext = msg.get("result_text", "")
        targs = msg.get("args", {})
        status = msg.get("status")
        if not ttype and not target and not targs and status == "cancelled":
            return None
        if status == "running":
            task_id = None
            if "[Background Task ID:" in (rtext or ""):
                import re

                bg_m = re.search(r"Background Task ID:\s*([^\s\]]+)", rtext)
                if bg_m:
                    task_id = bg_m.group(1)
            mgr = task_manager
            is_live = bool(task_id and mgr is not None and getattr(mgr, "_tasks", {}).get(task_id) is not None)
            if not is_live:
                status = "done" if rtext else "cancelled"
        elif not status and not rtext:
            status = "cancelled"
        return await chat_view.add_tool_call(
            ttype,
            target,
            result_text=rtext,
            args=targs,
            status=status,
            returncode=msg.get("returncode"),
            animate=False,
            **kw,
        )
    elif mtype == "event_divider":
        ctxt = msg.get("text", "Session Compacted")
        return await chat_view.add_event_divider(ctxt, animate=False, **kw)
    return None


class ChatView(VerticalScroll):
    """Scrollable chat stream with virtualized pagination / auto-loading"""

    PAGE_SIZE: int = 50
    can_focus = False

    def __init__(self, *args, show_welcome: bool = True, **kwargs):
        _apply_chat_markdown_patches()
        super().__init__(*args, **kwargs)
        self.show_welcome = show_welcome
        self._is_loading_session: bool = False
        self._unloaded_messages: list[dict] = []
        self._is_loading_older: bool = False
        # Bottom-follow intent. Cleared by an upward wheel tick, restored by
        # scrolling back to the bottom or by sending a new message.
        self._auto_follow: bool = True
        self.auto_expand_all: bool = False
        self._has_welcome: bool = False

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

    def scroll_up_page(self) -> None:
        """Scroll chat up by one page and pause auto-follow."""
        if self.max_scroll_y > 0:
            self._auto_follow = False
        self.scroll_page_up(animate=False)

    def scroll_down_page(self) -> None:
        """Scroll chat down by one page and resume auto-follow if bottom reached."""
        self.scroll_page_down(animate=False)
        self.call_after_refresh(self._resume_follow_if_at_bottom)

    def scroll_to_top(self) -> None:
        """Scroll chat to top and pause auto-follow."""
        if self.max_scroll_y > 0:
            self._auto_follow = False
        self.scroll_home(animate=False)

    def scroll_to_bottom(self) -> None:
        """Scroll chat to bottom and re-enable auto-follow."""
        self.scroll_end(animate=False)
        self._auto_follow = True

    def on_mount(self) -> None:
        self.check_welcome()

    def clear_welcome(self) -> None:
        welcomes = [c for c in self.children if isinstance(c, WelcomeWidget)]
        if not welcomes:
            try:
                welcomes = list(self.query(WelcomeWidget))
            except Exception:
                welcomes = []
        for w in welcomes:
            try:
                w.remove()
            except Exception:
                pass
        self._has_welcome = False

    def check_welcome(self) -> None:
        if not getattr(self, "show_welcome", True):
            self.clear_welcome()
            return
        welcomes = [c for c in self.children if isinstance(c, WelcomeWidget)]
        if not welcomes:
            try:
                welcomes = list(self.query(WelcomeWidget))
            except Exception:
                welcomes = []
        msg_children = [c for c in self.children if not isinstance(c, WelcomeWidget)]
        if not msg_children:
            if not welcomes:
                self.mount(WelcomeWidget())
                self._has_welcome = True
            else:
                self._has_welcome = True
        else:
            for w in welcomes:
                try:
                    w.remove()
                except Exception:
                    pass
            self._has_welcome = False

    def watch_scroll_y(self, old_val: float, new_val: float) -> None:
        if (
            new_val <= 2
            and old_val > new_val
            and self.has_older_messages()
            and not self._is_loading_older
            and not self._is_loading_session
        ):
            self.load_older_messages()

    def has_older_messages(self) -> bool:
        """True if there are older session messages that haven't been mounted yet."""
        return bool(self._unloaded_messages)

    def load_older_messages(self) -> None:
        """Trigger loading and mounting the next batch of older messages."""
        if self._is_loading_older or not self._unloaded_messages:
            return
        if hasattr(self, "run_worker") and callable(self.run_worker):
            try:
                self.run_worker(self._load_older_messages_worker(), exclusive=True)
                return
            except Exception:
                pass
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._load_older_messages_worker())
        except RuntimeError:
            pass

    async def load_all_older_messages(self) -> None:
        """Load and mount all remaining older messages into view."""
        while self.has_older_messages():
            await self._load_older_messages_worker()

    def get_total_user_message_count(self) -> int:
        """Return total count of visible user turns (both unloaded and mounted)."""
        unloaded_count = sum(
            1
            for m in self._unloaded_messages
            if isinstance(m, dict) and m.get("type") == "user" and is_ui_visible_user_message(m)
        )
        mounted_count = sum(1 for c in self.children if isinstance(c, UserMessage))
        return unloaded_count + mounted_count

    async def _load_older_messages_worker(self) -> None:
        if self._is_loading_older or not self._unloaded_messages:
            return
        self._is_loading_older = True
        self._auto_follow = False
        try:
            chunk = self._unloaded_messages[-self.PAGE_SIZE :]
            self._unloaded_messages = self._unloaded_messages[: -self.PAGE_SIZE]
            anchor = next((c for c in self.children if not isinstance(c, WelcomeWidget)), None)
            task_mgr = getattr(getattr(self, "app", None), "task_manager", None)
            if anchor is None:
                for msg in chunk:
                    await self.restore_message(msg, task_manager=task_mgr)
            else:
                for msg in chunk:
                    await self.restore_message(msg, before=anchor, task_manager=task_mgr)
                if anchor.is_attached:
                    try:
                        self.scroll_to_widget(anchor, top=True, animate=False)
                        self.call_after_refresh(lambda: self.scroll_to_widget(anchor, top=True, animate=False))
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Failed loading older chat messages: %s", e)
        finally:
            self._is_loading_older = False

    async def restore_message(self, msg: dict, before: Any = None, task_manager: Any = None) -> Any:
        """Restore a single message item dict into this view."""
        return await restore_message_item(self, msg, before=before, task_manager=task_manager)

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
        before: Any = None,
    ):
        """Mount ``widget`` and optionally snap to the bottom.

        Auto-follow scrolls are always instant: animated scrolls get superseded
        by the next debounced stream flush (~50ms) and leave the tail jittering.
        """
        if getattr(self, "_has_welcome", False) or any(isinstance(c, WelcomeWidget) for c in self.children):
            self.clear_welcome()
        if not self.is_attached:
            await self._wait_until_attached()
        if before is not None:
            await self.mount(widget, before=before)
        else:
            await self.mount(widget)
        if should_scroll and before is None:
            self.call_after_refresh(self.scroll_end, animate=animate)
        return widget

    async def add_user_message(
        self,
        text: str,
        animate: bool = False,
        attachments: list = None,
        attachments_count: int = 0,
        before: Any = None,
    ) -> UserMessage:
        att_count = attachments_count or (len(attachments) if attachments else 0)
        if att_count > 0:
            img_s = "s" if att_count > 1 else ""
            att_text = f"└─ {att_count} image{img_s} attached"
            msg = UserMessage(text or "", attachment_text=att_text, markup=False)
        else:
            msg = UserMessage(text or "", markup=False)

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
    ) -> ThinkingWidget:
        widget = ThinkingWidget(thinking_text)
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
    ) -> ToolCallWidget:
        last_child = None
        children_to_check = self.children if before is None else [c for c in self.children if c != before]
        for child in reversed(children_to_check):
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
