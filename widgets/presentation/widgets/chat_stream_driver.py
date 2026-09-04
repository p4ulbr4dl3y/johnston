"""Unified stream presenter/driver for ChatView.

Provides a single authoritative controller for rendering stream steps (generator-driven,
e.g. main agent in ai_generator) and session events (listener/history-driven, e.g.
subagent screen and history playback) into ChatView widgets without duplication.
"""
from __future__ import annotations

import inspect
import logging
import math
from collections import deque
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
        self.tool_handles: deque[ToolCallWidget] = deque()

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

    def cleanup_unfinalized_tools(self, error_message: Optional[str] = "Interrupted") -> None:
        """Mark or remove any unfinalized (generating or running) tool widgets."""
        while self.tool_handles:
            th = self.tool_handles.popleft()
            st = getattr(th, "status", None)
            if st == "generating":
                try:
                    th.remove()
                except Exception:
                    try:
                        th.mark_cancelled()
                    except Exception:
                        pass
            elif st == "running":
                msg = error_message or "Interrupted"
                try:
                    th.set_result(msg, is_error=True, status="error")
                except Exception:
                    pass

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
        elif event_type == "tool_generating":
            self.finalize_thinking_stream()
            await self.finalize_bot_stream()
            meta = val3 if isinstance(val3, dict) else {}
            tool_handle = await self.chat_view.add_tool_call(val1, val2, args={}, status="generating")
            if hasattr(tool_handle, "tool_call_id") or isinstance(meta, dict):
                setattr(tool_handle, "tool_call_id", meta.get("id"))
                setattr(tool_handle, "tool_call_index", meta.get("index"))
            self.tool_handles.append(tool_handle)
            if self.on_tool_widget:
                self.on_tool_widget(tool_handle)
        elif event_type == "tool_generating_update":
            meta = val3 if isinstance(val3, dict) else {}
            target_id = meta.get("id")
            target_idx = meta.get("index")
            matched = False
            if target_id:
                for th in self.tool_handles:
                    if getattr(th, "status", None) == "generating" and getattr(th, "tool_call_id", None) == target_id:
                        if hasattr(th, "update_tool_call"):
                            th.update_tool_call(target=val2)
                        matched = True
                        break
            if not matched and target_idx is not None:
                for th in self.tool_handles:
                    if getattr(th, "status", None) == "generating" and getattr(th, "tool_call_index", None) == target_idx:
                        if hasattr(th, "update_tool_call"):
                            th.update_tool_call(target=val2)
                        matched = True
                        break
            if not matched and not target_id and target_idx is None:
                for th in self.tool_handles:
                    if getattr(th, "status", None) == "generating":
                        if hasattr(th, "update_tool_call"):
                            th.update_tool_call(target=val2)
                        break
        elif event_type == "tool":
            self.finalize_thinking_stream()
            await self.finalize_bot_stream()
            targs = val3 if isinstance(val3, dict) else {}
            tool_id = step[4] if len(step) > 4 else None
            gen_handle = None
            if tool_id:
                for th in self.tool_handles:
                    if getattr(th, "status", None) == "generating" and getattr(th, "tool_call_id", None) == tool_id:
                        gen_handle = th
                        break
            if gen_handle is None:
                for th in self.tool_handles:
                    if getattr(th, "status", None) == "generating" and (
                        getattr(th, "canonical_tool", None) == val1
                        or getattr(th, "tool_type", None) == val1
                    ):
                        gen_handle = th
                        break
            if gen_handle is None:
                for th in self.tool_handles:
                    if getattr(th, "status", None) == "generating":
                        gen_handle = th
                        break
            if gen_handle is not None:
                if hasattr(gen_handle, "update_tool_call"):
                    gen_handle.update_tool_call(target=val2, args=targs)
                if hasattr(gen_handle, "mark_running"):
                    gen_handle.mark_running()
                tool_handle = gen_handle
            else:
                tool_handle = await self.chat_view.add_tool_call(val1, val2, args=targs)
                if tool_id:
                    setattr(tool_handle, "tool_call_id", tool_id)
                self.tool_handles.append(tool_handle)
            if self.on_tool_widget:
                self.on_tool_widget(tool_handle)
        elif event_type == "tool_result":
            parsed_tool_result = parse_tool_result_step(step)
            res_status = parsed_tool_result.status.value if parsed_tool_result.status is not None else None
            tool_id = step[6] if len(step) > 6 else None
            cur_tool_handle = None

            if tool_id:
                for th in self.tool_handles:
                    if getattr(th, "tool_call_id", None) == tool_id:
                        cur_tool_handle = th
                        self.tool_handles.remove(th)
                        break

            if cur_tool_handle is None:
                while self.tool_handles:
                    st = getattr(self.tool_handles[0], "status", None)
                    if isinstance(st, str) and st not in ("running", "generating"):
                        self.tool_handles.popleft()
                    else:
                        break
                if self.tool_handles:
                    cur_tool_handle = self.tool_handles.popleft()

            if cur_tool_handle is not None:
                cur_tool_handle.set_result(
                    val1,
                    is_error=parsed_tool_result.is_error,
                    status=res_status,
                    returncode=parsed_tool_result.returncode,
                )
            else:
                if tool_id:
                    for child in reversed(list(getattr(self.chat_view, "children", []))):
                        if isinstance(child, ToolCallWidget) and getattr(child, "tool_call_id", None) == tool_id:
                            cur_tool_handle = child
                            break
                if cur_tool_handle is None:
                    for child in reversed(list(getattr(self.chat_view, "children", []))):
                        if isinstance(child, ToolCallWidget) and getattr(child, "status", None) in ("running", "generating"):
                            cur_tool_handle = child
                            break
                if cur_tool_handle is not None:
                    cur_tool_handle.set_result(
                        val1,
                        is_error=parsed_tool_result.is_error,
                        status=res_status,
                        returncode=parsed_tool_result.returncode,
                    )
                else:
                    logger.debug("Received tool_result step with empty tool_handles queue: %s", val1)
        elif event_type == "bot_delta":
            self.finalize_thinking_stream()
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
            # Clean up zombie generating widgets from failed attempt
            remaining_handles = deque()
            while self.tool_handles:
                th = self.tool_handles.popleft()
                if getattr(th, "status", None) == "generating":
                    try:
                        th.remove()
                    except Exception:
                        pass
                else:
                    remaining_handles.append(th)
            self.tool_handles = remaining_handles
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
            self.finalize_thinking_stream()
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
            self.finalize_thinking_stream()
            err_text = val1 or "Error"
            await self.chat_view.add_error_message(err_text)
        elif event_type == "event_divider":
            self.finalize_thinking_stream()
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
        elif etype == "tool_generating":
            self.finalize_thinking_stream()
            await self.finalize_bot_stream()
            meta = evt.get("meta") if isinstance(evt.get("meta"), dict) else {}
            tool_handle = await self.chat_view.add_tool_call(
                evt.get("tool_type", ""),
                evt.get("target", ""),
                args={},
                status="generating",
            )
            if hasattr(tool_handle, "tool_call_id") or isinstance(meta, dict):
                setattr(tool_handle, "tool_call_id", meta.get("id"))
                setattr(tool_handle, "tool_call_index", meta.get("index"))
            self.tool_handles.append(tool_handle)
            if self.on_tool_widget:
                self.on_tool_widget(tool_handle)
        elif etype == "tool_generating_update":
            meta = evt.get("meta") if isinstance(evt.get("meta"), dict) else {}
            target_id = meta.get("id")
            target_idx = meta.get("index")
            target = evt.get("target", "")
            matched = False
            if target_id:
                for th in self.tool_handles:
                    if getattr(th, "status", None) == "generating" and getattr(th, "tool_call_id", None) == target_id:
                        if hasattr(th, "update_tool_call"):
                            th.update_tool_call(target=target)
                        matched = True
                        break
            if not matched and target_idx is not None:
                for th in self.tool_handles:
                    if getattr(th, "status", None) == "generating" and getattr(th, "tool_call_index", None) == target_idx:
                        if hasattr(th, "update_tool_call"):
                            th.update_tool_call(target=target)
                        matched = True
                        break
            if not matched and not target_id and target_idx is None:
                for th in self.tool_handles:
                    if getattr(th, "status", None) == "generating":
                        if hasattr(th, "update_tool_call"):
                            th.update_tool_call(target=target)
                        break
        elif etype == "tool_shell_output":
            txt = evt.get("text", "")
            target_th = self.tool_handles[-1] if self.tool_handles else None
            if target_th is None:
                for child in reversed(list(getattr(self.chat_view, "children", []))):
                    if isinstance(child, ToolCallWidget) and getattr(child, "status", None) in ("running", "generating"):
                        target_th = child
                        break
            if target_th and hasattr(target_th, "append_shell_output"):
                target_th.append_shell_output(txt)
        elif etype == "tool":
            self.finalize_thinking_stream()
            # Check if this event is a completion event for an in-flight tool
            if "result_text" in evt and not evt.get("tool_type"):
                while self.tool_handles:
                    st = getattr(self.tool_handles[0], "status", None)
                    if isinstance(st, str) and st not in ("running", "generating"):
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
                        if isinstance(child, ToolCallWidget) and getattr(child, "status", None) in ("running", "generating"):
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
                targs = evt.get("args", {})
                tool_type = evt.get("tool_type", "")
                target = evt.get("target", "")
                tool_id = evt.get("tool_id") or (evt.get("meta", {}).get("id") if isinstance(evt.get("meta"), dict) else None)
                gen_handle = None
                if tool_id:
                    for th in self.tool_handles:
                        if getattr(th, "status", None) == "generating" and getattr(th, "tool_call_id", None) == tool_id:
                            gen_handle = th
                            break
                if gen_handle is None:
                    for th in self.tool_handles:
                        if getattr(th, "status", None) == "generating" and (
                            getattr(th, "canonical_tool", None) == tool_type
                            or getattr(th, "tool_type", None) == tool_type
                        ):
                            gen_handle = th
                            break
                if gen_handle is None:
                    for th in self.tool_handles:
                        if getattr(th, "status", None) == "generating":
                            gen_handle = th
                            break
                if gen_handle is not None:
                    if hasattr(gen_handle, "update_tool_call"):
                        gen_handle.update_tool_call(target=target, args=targs)
                    if hasattr(gen_handle, "mark_running"):
                        gen_handle.mark_running()
                    widget = gen_handle
                else:
                    tool_kw = {"args": targs}
                    if not evt.get("from_stream_step"):
                        tool_kw["result_text"] = evt.get("result_text", "")
                        tool_kw["status"] = evt.get("status")
                        tool_kw["returncode"] = evt.get("returncode")
                        tool_kw["animate"] = animate
                    widget = await self.chat_view.add_tool_call(
                        tool_type,
                        target,
                        **tool_kw,
                    )
                    if tool_id:
                        setattr(widget, "tool_call_id", tool_id)
                    # Track in tool_handles only if the tool is actively in-flight (uncompleted)
                    if "result_text" not in evt and evt.get("status") not in ("done", "error", "cancelled"):
                        self.tool_handles.append(widget)
                if is_expanded and hasattr(widget, "is_expandable") and widget.is_expandable():
                    widget.is_expanded = True
                if self.on_tool_widget:
                    self.on_tool_widget(widget)
                if animate and tool_type == "update_plan" and self.on_plan_update:
                    if isinstance(targs, dict) and isinstance(targs.get("plan"), list):
                        self.on_plan_update(targs.get("plan", []), targs.get("explanation", ""))
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
