"""Unified stream presenter/driver for ChatView.

Single authoritative controller that renders stream steps, session events and
history playback through one state machine (``consume_session_event``).

``consume_stream_step`` (generator-driven, e.g. main agent in ai_generator)
canonicalizes raw step tuples via ``stream_step_to_session_event`` and
delegates to the same ``consume_session_event`` path used by session listeners
(subagent screen) and history replay — live streaming and replay can never
drift apart, and the step protocol is parsed in exactly one place.
"""
from __future__ import annotations

import inspect
import logging
import math
from collections import deque
from typing import Any, Callable, Optional

from core.application.session.stream import stream_step_to_session_event
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
        # Running tool cards that were in flight when a retry was issued. They
        # are removed from the FIFO queue so a stale result cannot misattach,
        # but stay mounted awaiting finalization (status_change/error, reuse by
        # a re-issued tool event, or turn cleanup).
        self._pending_running_after_retry: list = []

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
        self._pending_running_after_retry.clear()

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
        # The retried turn finished without a result for these running cards.
        while self._pending_running_after_retry:
            th = self._pending_running_after_retry.pop(0)
            if getattr(th, "status", None) == "running":
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
        """Consume a raw generator step tuple from BaseAgent.stream_steps.

        Canonicalizes the tuple via :func:`stream_step_to_session_event` and
        renders through ``consume_session_event`` — the same state machine used
        for session listeners and history replay.
        """
        evt = stream_step_to_session_event(step, from_stream_step=True)
        if evt is None:
            return
        await self.consume_session_event(evt, animate=True, is_active=True)

    def _match_tool_result_widget(self, evt: dict) -> Optional[ToolCallWidget]:
        """Find the tool card a completion event belongs to.

        Resolution order:
        1. explicit ``tool_id`` match against the in-flight queue;
        2. FIFO — results arrive in the order the calls were announced;
        3. mounted children by ``tool_call_id``, then any live child.
        """
        tool_id = evt.get("tool_id")
        if tool_id:
            for th in self.tool_handles:
                if getattr(th, "tool_call_id", None) == tool_id:
                    self.tool_handles.remove(th)
                    return th
        # Replay-path events carry tool_type but no tool_id (the pairing id was
        # renamed to tool_call_id when persisted) — match a live card by type.
        if evt.get("tool_type") and not tool_id:
            for th in self.tool_handles:
                if getattr(th, "status", None) in ("running", "generating") and (
                    getattr(th, "canonical_tool", None) == evt["tool_type"]
                    or getattr(th, "tool_type", None) == evt["tool_type"]
                ):
                    self.tool_handles.remove(th)
                    return th
        while self.tool_handles:
            st = getattr(self.tool_handles[0], "status", None)
            if isinstance(st, str) and st not in ("running", "generating"):
                self.tool_handles.popleft()
            else:
                break
        if self.tool_handles:
            return self.tool_handles.popleft()
        children = list(getattr(self.chat_view, "children", []))
        if tool_id:
            for child in reversed(children):
                if isinstance(child, ToolCallWidget) and getattr(child, "tool_call_id", None) == tool_id:
                    return child
        for child in reversed(children):
            if isinstance(child, ToolCallWidget) and getattr(child, "status", None) in ("running", "generating"):
                return child
        return None

    def _find_shell_output_target(self) -> Optional[ToolCallWidget]:
        """Locate the tool card that owns a shell output chunk.

        Prefers a mounted child linked to a background shell task, then the
        newest live shell card, then any live (running/generating) card, then a
        live mounted child — never a completed card, so output from a
        background shell cannot land on a stale neighbour.
        """
        for child in reversed(list(getattr(self.chat_view, "children", []))):
            if isinstance(child, ToolCallWidget) and getattr(child, "background_task_id", None):
                return child
        for th in reversed(self.tool_handles):
            st = getattr(th, "status", None)
            if st in ("running", "generating") and getattr(th, "canonical_tool", None) == "shell":
                return th
        for th in reversed(self.tool_handles):
            if getattr(th, "status", None) in ("running", "generating"):
                return th
        for child in reversed(list(getattr(self.chat_view, "children", []))):
            if isinstance(child, ToolCallWidget) and getattr(child, "status", None) in ("running", "generating"):
                return child
        return None

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
                    if getattr(th, "status", None) in ("generating", "running") and getattr(
                        th, "tool_call_id", None
                    ) == target_id:
                        if hasattr(th, "update_tool_call"):
                            th.update_tool_call(target=target)
                        matched = True
                        break
            if not matched and target_idx is not None:
                for th in self.tool_handles:
                    if getattr(th, "status", None) in ("generating", "running") and getattr(
                        th, "tool_call_index", None
                    ) == target_idx:
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
            target_th = self._find_shell_output_target()
            if target_th is not None and hasattr(target_th, "append_shell_output"):
                target_th.append_shell_output(txt)
        elif etype == "tool":
            self.finalize_thinking_stream()
            # Completion events — live tool_result (no tool_type) and replay
            # result events (tool_type present, pairing id renamed to
            # tool_call_id) — are matched to a live card first.
            result_handled = False
            if "result_text" in evt:
                w = self._match_tool_result_widget(evt)
                if w is not None:
                    w.set_result(
                        evt.get("result_text", ""),
                        is_error=bool(evt.get("is_error", False)),
                        status=evt.get("status"),
                        returncode=evt.get("returncode"),
                    )
                    result_handled = True
                elif not evt.get("tool_type"):
                    result_handled = True
                    logger.debug("Received session tool_result event with empty tool_handles queue: %s", evt)
            if not result_handled:
                # Live tool start, or a completed history event (tool_type +
                # result_text) with no live card to update: render it here.
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
                    # The retried turn re-issued a tool that was running when
                    # the retry landed: reuse its mounted card instead of
                    # creating a duplicate; abandoned cards get finalized.
                    pending_reused = None
                    for th in self._pending_running_after_retry:
                        if getattr(th, "status", None) != "running":
                            continue
                        match_id = tool_id and getattr(th, "tool_call_id", None) == tool_id
                        match_type = bool(tool_type) and (
                            getattr(th, "canonical_tool", None) == tool_type
                            or getattr(th, "tool_type", None) == tool_type
                        )
                        if match_id or match_type:
                            pending_reused = th
                            break
                    if pending_reused is not None:
                        self._pending_running_after_retry.remove(pending_reused)
                        gen_handle = pending_reused
                        if hasattr(gen_handle, "update_tool_call"):
                            gen_handle.update_tool_call(target=target, args=targs)
                        if hasattr(gen_handle, "mark_running"):
                            gen_handle.mark_running()
                        widget = gen_handle
                        # Re-track in the FIFO so a later result matches by id.
                        if "result_text" not in evt and evt.get("status") not in ("done", "error", "cancelled"):
                            self.tool_handles.append(widget)
                    else:
                        while self._pending_running_after_retry:
                            abandoned = self._pending_running_after_retry.pop(0)
                            if getattr(abandoned, "status", None) == "running":
                                try:
                                    abandoned.mark_cancelled()
                                except Exception:
                                    pass
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
                    if hasattr(widget, "set_expanded"):
                        widget.set_expanded(True, scroll=False)
                    else:
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
            # Drop zombie generating cards from the failed attempt. Handles that
            # were already running are pulled out of the FIFO (so a stale result
            # cannot misattach) but kept mounted; they are finalized by a
            # status_change/error, re-used by a re-issued tool event, or cleaned
            # up at turn end.
            remaining_handles = deque()
            while self.tool_handles:
                th = self.tool_handles.popleft()
                if getattr(th, "status", None) == "generating":
                    try:
                        th.remove()
                    except Exception:
                        pass
                elif getattr(th, "status", None) == "running":
                    self._pending_running_after_retry.append(th)
                else:
                    remaining_handles.append(th)
            self.tool_handles = remaining_handles
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
                # Finalize running cards orphaned by a retry that dropped them.
                while self._pending_running_after_retry:
                    w = self._pending_running_after_retry.pop(0)
                    if hasattr(w, "mark_cancelled"):
                        try:
                            w.mark_cancelled()
                        except Exception:
                            pass
        elif etype == "error":
            self.finalize_thinking_stream()
            err_kw = {} if evt.get("from_stream_step") else {"animate": animate}
            await self.chat_view.add_error_message(evt.get("text", "Error"), **err_kw)
        elif etype == "event_divider":
            self.finalize_thinking_stream()
            div_kw = {} if evt.get("from_stream_step") else {"animate": animate}
            await self.chat_view.add_event_divider(evt.get("text", "Session Compacted"), **div_kw)
