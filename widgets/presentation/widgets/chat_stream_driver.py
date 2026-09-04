"""Unified stream presenter/driver for ChatView.

Provides a single authoritative controller for rendering stream steps (generator-driven,
e.g. main agent in ai_generator) and session events (listener/history-driven, e.g.
subagent screen and history playback) into ChatView widgets without duplication.
"""
from __future__ import annotations

import collections
import inspect
import logging
import math
from typing import Any, Callable, Optional

from core.domain.policies.messages import is_ui_visible_user_message
from widgets.chat_toolcall import ToolCallWidget
from widgets.presentation.widgets.chat_messages import BotMessage, ThinkingWidget

logger = logging.getLogger(__name__)


class ChatStreamDriver:
    """Stateful stream and event controller for ChatView."""

    def __init__(
        self,
        chat_view: Any,
        *,
        on_tool_widget: Optional[Callable[[ToolCallWidget], Any]] = None,
        on_plan_update: Optional[Callable[[list, str], Any]] = None,
        notify: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.chat_view = chat_view
        self.on_tool_widget = on_tool_widget
        self.on_plan_update = on_plan_update
        self.notify = notify
        self.bot_handle: Optional[BotMessage] = None
        self.thinking_handle: Optional[ThinkingWidget] = None
        self.tool_handles: collections.deque[ToolCallWidget] = collections.deque()

    def finalize_thinking_stream(self, duration: float = 0.0, content: str = "") -> None:
        """Finalize any in-flight thinking widget."""
        if self.thinking_handle is not None:
            if hasattr(self.thinking_handle, "finish_thinking"):
                try:
                    self.thinking_handle.finish_thinking(duration, content)
                except Exception:
                    pass
            self.thinking_handle = None

    def reset(self) -> None:
        """Reset internal handles and queue state."""
        self.finalize_thinking_stream()
        self.bot_handle = None
        self.tool_handles.clear()

    async def finalize_bot_stream(self) -> None:
        """Finalize or clean up in-flight bot streaming content."""
        if self.bot_handle is not None:
            if hasattr(self.bot_handle, "flush_pending_stream"):
                try:
                    self.bot_handle.flush_pending_stream()
                except Exception:
                    pass
            content_str = getattr(self.bot_handle, "content", "")
            stream_parts = getattr(self.bot_handle, "_stream_parts", None)
            if isinstance(stream_parts, list) and stream_parts and hasattr(self.bot_handle, "_join_stream_content"):
                content_str = self.bot_handle._join_stream_content()
            content_val = str(content_str) if not isinstance(content_str, str) else content_str
            if not content_val.strip():
                if hasattr(self.bot_handle, "remove"):
                    try:
                        self.bot_handle.remove()
                    except Exception:
                        pass
            elif hasattr(self.bot_handle, "finalize_stream"):
                res = self.bot_handle.finalize_stream()
                if inspect.isawaitable(res):
                    await res
            self.bot_handle = None

    async def consume_stream_step(self, step: tuple) -> None:
        """Consume a raw generator step tuple from BaseAgent.stream_steps.

        Translates raw tuple to a canonical session event and delegates to
        consume_session_event for unified presentation logic.
        """
        if not step:
            return
        from core.application.session.stream import stream_step_to_session_event

        evt = stream_step_to_session_event(step, from_stream_step=True)
        if evt is not None:
            await self.consume_session_event(evt, animate=True, is_active=True)

    async def consume_session_event(
        self,
        evt: dict,
        *,
        animate: bool = True,
        is_expanded: bool = False,
        is_active: bool = False,
    ) -> None:
        """Consume a canonical session event dict (from history, live session listener, or stream step)."""
        if not isinstance(evt, dict):
            return
        etype = evt.get("type")

        if etype == "user":
            if not is_ui_visible_user_message(evt):
                return
            att_count = evt.get("attachments_count", 0)
            if not att_count and evt.get("attachments"):
                att_count = len(evt.get("attachments"))
            await self.chat_view.add_user_message(
                evt.get("display_text") or evt.get("text", ""),
                animate=animate,
                attachments_count=att_count,
            )
        elif etype == "thinking":
            txt = evt.get("text", "")
            phase = evt.get("phase")
            dur = evt.get("duration")

            if self.thinking_handle is None:
                if evt.get("from_stream_step"):
                    self.thinking_handle = await self.chat_view.add_thinking_widget(txt)
                else:
                    self.thinking_handle = await self.chat_view.add_thinking_widget(txt, animate=animate)
                if is_expanded and hasattr(self.thinking_handle, "is_expandable") and self.thinking_handle.is_expandable():
                    self.thinking_handle.is_expanded = True
            else:
                if hasattr(self.thinking_handle, "update_thinking"):
                    self.thinking_handle.update_thinking(txt)

            # Finalize thinking when:
            # 1. Explicit duration is present (thought finished), OR
            # 2. Phase is explicitly 'end', OR
            # 3. Inactive historical replay without animation (unclosed thought in saved history)
            if dur is not None or phase == "end" or (not is_active and not animate):
                if dur is None or not math.isfinite(dur):
                    dur = 0.0
                if hasattr(self.thinking_handle, "finish_thinking"):
                    self.thinking_handle.finish_thinking(dur, txt)
                self.thinking_handle = None
        elif etype == "tool":
            self.finalize_thinking_stream()
            # Check if this event is a completion event for an in-flight tool
            if "result_text" in evt and not evt.get("tool_type"):
                while self.tool_handles:
                    st = getattr(self.tool_handles[0], "status", None)
                    if isinstance(st, str) and st not in ("running",):
                        self.tool_handles.popleft()
                    else:
                        break
                if self.tool_handles:
                    w = self.tool_handles.popleft()
                    w.set_result(
                        evt.get("result_text", ""),
                        is_error=bool(evt.get("is_error", False)),
                        status=evt.get("status"),
                        returncode=evt.get("returncode"),
                    )
                else:
                    for child in reversed(list(getattr(self.chat_view, "children", []))):
                        if isinstance(child, ToolCallWidget) and getattr(child, "status", None) == "running":
                            child.set_result(
                                evt.get("result_text", ""),
                                is_error=bool(evt.get("is_error", False)),
                                status=evt.get("status"),
                                returncode=evt.get("returncode"),
                            )
                            break
                    logger.debug("Received session tool_result event with empty tool_handles queue: %s", evt)
            else:
                await self.finalize_bot_stream()
                tool_kw = {"args": evt.get("args", {})}
                if not evt.get("from_stream_step"):
                    tool_kw["result_text"] = evt.get("result_text", "")
                    tool_kw["status"] = evt.get("status")
                    tool_kw["returncode"] = evt.get("returncode")
                    tool_kw["animate"] = animate
                widget = await self.chat_view.add_tool_call(
                    evt.get("tool_type", ""),
                    evt.get("target", ""),
                    **tool_kw,
                )
                if is_expanded and hasattr(widget, "is_expandable") and widget.is_expandable():
                    widget.is_expanded = True
                if self.on_tool_widget:
                    self.on_tool_widget(widget)
                if animate and evt.get("tool_type") == "update_plan" and self.on_plan_update:
                    args = evt.get("args") or {}
                    if isinstance(args, dict) and isinstance(args.get("plan"), list):
                        self.on_plan_update(args.get("plan", []), args.get("explanation", ""))
                # Track in tool_handles only if the tool is actively in-flight (uncompleted)
                if "result_text" not in evt and evt.get("status") not in ("done", "error", "cancelled"):
                    self.tool_handles.append(widget)
        elif etype == "bot":
            self.finalize_thinking_stream()
            txt = evt.get("text", "")
            delta = evt.get("delta")
            if not animate and not is_active and not txt.strip():
                return
            if txt or delta:
                if self.bot_handle is None:
                    if evt.get("from_stream_step"):
                        self.bot_handle = await self.chat_view.add_bot_message()
                    else:
                        self.bot_handle = await self.chat_view.add_bot_message(animate=animate or is_active)
                if evt.get("final") or (not animate and not is_active):
                    if evt.get("from_stream_step"):
                        if hasattr(self.bot_handle, "finalize_stream"):
                            res = self.bot_handle.finalize_stream(txt)
                            if inspect.isawaitable(res):
                                await res
                        elif hasattr(self.bot_handle, "set_final_content"):
                            res = self.bot_handle.set_final_content(txt)
                            if inspect.isawaitable(res):
                                await res
                    else:
                        if hasattr(self.bot_handle, "set_final_content"):
                            res = self.bot_handle.set_final_content(txt)
                            if inspect.isawaitable(res):
                                await res
                        elif hasattr(self.bot_handle, "finalize_stream"):
                            res = self.bot_handle.finalize_stream(txt)
                            if inspect.isawaitable(res):
                                await res
                    self.bot_handle = None
                else:
                    if delta and hasattr(self.bot_handle, "append_stream_content"):
                        self.bot_handle.append_stream_content(delta)
                    elif hasattr(self.bot_handle, "set_stream_content"):
                        self.bot_handle.set_stream_content(txt)
        elif etype == "bot_reset":
            if self.bot_handle is not None and hasattr(self.bot_handle, "reset_stream"):
                try:
                    res = self.bot_handle.reset_stream()
                    if inspect.isawaitable(res):
                        await res
                except Exception:
                    pass
        elif etype == "retry":
            if self.bot_handle is not None and hasattr(self.bot_handle, "reset_stream"):
                try:
                    res = self.bot_handle.reset_stream()
                    if inspect.isawaitable(res):
                        await res
                except Exception:
                    pass
            if self.notify:
                attempt = evt.get("attempt") or 1
                max_retries = evt.get("max_retries") or 3
                delay = evt.get("delay") or 0.0
                err = evt.get("error")
                err_msg = str(err).lower() if err else ""
                is_rate_limit = (
                    "rate limit" in err_msg
                    or "429" in err_msg
                    or getattr(err, "status_code", None) == 429
                )
                reason = "Rate limit reached" if is_rate_limit else "Provider error"
                try:
                    self.notify(
                        f"{reason}: retrying in {max(1, int(round(delay)))}s (attempt {attempt}/{max_retries})",
                        severity="warning",
                    )
                except Exception:
                    pass
        elif etype == "status_change":
            self.finalize_thinking_stream()
            await self.finalize_bot_stream()
            status = evt.get("status")
            if status in ("cancelled", "error"):
                while self.tool_handles:
                    w = self.tool_handles.popleft()
                    if hasattr(w, "mark_cancelled"):
                        w.mark_cancelled()
        elif etype == "error":
            self.finalize_thinking_stream()
            err_kw = {} if evt.get("from_stream_step") else {"animate": animate}
            await self.chat_view.add_error_message(evt.get("text", "Error"), **err_kw)
        elif etype == "event_divider":
            self.finalize_thinking_stream()
            div_kw = {} if evt.get("from_stream_step") else {"animate": animate}
            await self.chat_view.add_event_divider(evt.get("text", "Session Compacted"), **div_kw)
