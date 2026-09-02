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

from core.domain.defaults.errors import parse_tool_result_step
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

    def reset(self) -> None:
        """Reset internal handles and queue state."""
        self.bot_handle = None
        self.thinking_handle = None
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
        """Consume a raw generator step tuple from BaseAgent.stream_steps."""
        if not step:
            return
        event_type = step[0]
        val1 = step[1] if len(step) > 1 else ""
        val2 = step[2] if len(step) > 2 else ""
        val3 = step[3] if len(step) > 3 else None

        if event_type == "thinking_start":
            self.thinking_handle = await self.chat_view.add_thinking_widget(val1)
        elif event_type == "thinking_delta":
            if self.thinking_handle and hasattr(self.thinking_handle, "update_thinking"):
                self.thinking_handle.update_thinking(val1)
        elif event_type == "thinking_end":
            if self.thinking_handle:
                try:
                    duration = float(val1)
                    if not math.isfinite(duration):
                        duration = 0.0
                except Exception:
                    duration = 0.0
                if hasattr(self.thinking_handle, "finish_thinking"):
                    self.thinking_handle.finish_thinking(duration, val2)
            self.thinking_handle = None
        elif event_type == "tool":
            await self.finalize_bot_stream()
            targs = val3 if isinstance(val3, dict) else {}
            tool_handle = await self.chat_view.add_tool_call(val1, val2, args=targs)
            self.tool_handles.append(tool_handle)
            if self.on_tool_widget:
                self.on_tool_widget(tool_handle)
        elif event_type == "tool_result":
            if self.tool_handles:
                cur_tool_handle = self.tool_handles.popleft()
                parsed_tool_result = parse_tool_result_step(step)
                cur_tool_handle.set_result(
                    val1,
                    is_error=parsed_tool_result.is_error,
                    status=parsed_tool_result.status.value if parsed_tool_result.status is not None else None,
                    returncode=parsed_tool_result.returncode,
                )
            else:
                logger.debug("Received tool_result step with empty tool_handles queue: %s", val1)
        elif event_type == "bot_delta":
            if val1:
                if self.bot_handle is None:
                    self.bot_handle = await self.chat_view.add_bot_message()
                if hasattr(self.bot_handle, "append_stream_content"):
                    self.bot_handle.append_stream_content(val1)
        elif event_type == "bot_reset":
            if self.bot_handle is not None and hasattr(self.bot_handle, "reset_stream"):
                try:
                    res = self.bot_handle.reset_stream()
                    if inspect.isawaitable(res):
                        await res
                except Exception:
                    pass
        elif event_type == "retry":
            if self.bot_handle is not None and hasattr(self.bot_handle, "reset_stream"):
                try:
                    res = self.bot_handle.reset_stream()
                    if inspect.isawaitable(res):
                        await res
                except Exception:
                    pass
            if self.notify:
                attempt = val1
                max_retries = val2
                delay = val3 or 0.0
                err = step[4] if len(step) > 4 else None
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
        elif event_type in ("bot_text", "outro"):
            if val1.strip():
                if self.bot_handle is None:
                    self.bot_handle = await self.chat_view.add_bot_message()
                if hasattr(self.bot_handle, "finalize_stream"):
                    res = self.bot_handle.finalize_stream(val1)
                    if inspect.isawaitable(res):
                        await res
                self.bot_handle = None
            else:
                await self.finalize_bot_stream()
        elif event_type == "error":
            err_text = val1 or "Error"
            await self.chat_view.add_error_message(err_text)
        elif event_type == "event_divider":
            div_text = val1 or "Session Compacted"
            await self.chat_view.add_event_divider(div_text)

    async def consume_session_event(
        self,
        evt: dict,
        *,
        animate: bool = True,
        is_expanded: bool = False,
        is_active: bool = False,
    ) -> None:
        """Consume a canonical session event dict (from history or live session listener)."""
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
            if self.thinking_handle is None:
                self.thinking_handle = await self.chat_view.add_thinking_widget(txt, animate=animate)
                if is_expanded and hasattr(self.thinking_handle, "is_expandable") and self.thinking_handle.is_expandable():
                    self.thinking_handle.is_expanded = True
            else:
                if hasattr(self.thinking_handle, "update_thinking"):
                    self.thinking_handle.update_thinking(txt)
            if evt.get("duration") is not None:
                if hasattr(self.thinking_handle, "finish_thinking"):
                    self.thinking_handle.finish_thinking(evt.get("duration", 0.0), txt)
                self.thinking_handle = None
        elif etype == "tool":
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
                    logger.debug("Received session tool_result event with empty tool_handles queue: %s", evt)
            else:
                await self.finalize_bot_stream()
                widget = await self.chat_view.add_tool_call(
                    evt.get("tool_type", ""),
                    evt.get("target", ""),
                    result_text=evt.get("result_text", ""),
                    args=evt.get("args", {}),
                    status=evt.get("status"),
                    returncode=evt.get("returncode"),
                    animate=animate,
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
            txt = evt.get("text", "")
            if not animate and not is_active and not txt.strip():
                return
            if txt:
                if self.bot_handle is None:
                    self.bot_handle = await self.chat_view.add_bot_message(animate=animate or is_active)
                if evt.get("final") or (not animate and not is_active):
                    if hasattr(self.bot_handle, "set_final_content"):
                        res = self.bot_handle.set_final_content(txt)
                        if inspect.isawaitable(res):
                            await res
                    self.bot_handle = None
                else:
                    if hasattr(self.bot_handle, "set_stream_content"):
                        self.bot_handle.set_stream_content(txt)
        elif etype == "bot_reset":
            if self.bot_handle is not None and hasattr(self.bot_handle, "reset_stream"):
                try:
                    res = self.bot_handle.reset_stream()
                    if inspect.isawaitable(res):
                        await res
                except Exception:
                    pass
        elif etype == "error":
            await self.chat_view.add_error_message(evt.get("text", "Error"), animate=animate)
        elif etype == "event_divider":
            await self.chat_view.add_event_divider(evt.get("text", "Session Compacted"), animate=animate)
