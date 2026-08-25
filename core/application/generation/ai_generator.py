"""AI response generation engine, free of any Textual/widget dependency.

The engine orchestrates the agent ``stream_steps`` loop and owns all
non-rendering business logic: transcript recording (``AgentSession.add_event``),
git checkpoints, token accounting, cancellation/partial-history handling and
queue settling. Every interaction with the UI is funneled through a
:class:`GenCanvas` of callbacks injected by the caller (the
``MessageFlowMixin``), so this module is fully testable without Textual.
"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from core.application.session.stream import record_subagent_step
from core.domain.defaults.errors import parse_tool_result_step

logger = logging.getLogger(__name__)


class ProviderReadyState(Enum):
    """State of provider/model readiness before generating a response."""

    READY = "ready"
    NEEDS_PROVIDER = "provider"
    NEEDS_MODEL = "model"


class _SessionSaveDebounce:
    """Batches the many per-step save_session calls into one disk write per turn.

    The stream loop pushes save_session on every tool_result, every bot_text,
    and every event_divider. Most of those target the same in-memory transcript
    and only the final state matters for persistence, so coalescing them into a
    single call (trailing edge, after the step bursts settle) avoids hammering
    the store with near-identical writes.
    """

    def __init__(self, save_cb, settle_time: float = 0.4):
        self._save = save_cb
        self._settle = settle_time
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None

    def _ensure_loop(self) -> bool:
        try:
            self._loop = asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def schedule(self) -> None:
        """Debounced save: reset the timer on each call in a step burst."""
        if not self._save:
            return
        if self._task is not None and not self._task.done():
            self._task.cancel()
        if not self._ensure_loop():
            return
        self._task = self._loop.create_task(self._run())

    async def _run(self) -> None:
        try:
            await asyncio.sleep(self._settle)
            await self._save()
        except (asyncio.CancelledError, Exception):
            pass

    async def flush(self) -> None:
        """Coalesce any pending save into an immediate one (final upload)."""
        if self._task is not None:
            self._task.cancel()
        if not self._save:
            return
        if not self._ensure_loop():
            return
        await self._save()


@dataclass
class GenCanvas:
    """UI callback bundle injected by the Textual, mixin.

    Each field is a callable bound by the mixin to real widget operations.
    Handles returned by ``add_thinking_widget``/``add_tool_call``/``add_bot_message``
    are opaque UI handles the engine drives via their public methods.
    """

    add_user_message: Callable[[str, Any], Any] = field(default=None)
    add_thinking_widget: Callable[[str], Any] = field(default=None)
    add_tool_call: Callable[[str, str, Any], Any] = field(default=None)
    register_tool_widget: Callable[[Any], Any] = field(default=None)
    add_bot_message: Callable[[], Any] = field(default=None)
    add_event_divider: Callable[[str], Any] = field(default=None)
    get_user_messages: Callable[[], Any] = field(default=None)
    refresh_status_footer: Callable[[], Any] = field(default=None)
    notify: Callable[[str, str], Any] = field(default=None)
    save_session: Callable[..., Any] = field(default=None)


def ensure_provider_ready(pm: Any, agent: Any) -> Optional[ProviderReadyState]:
    """Check provider connection and model config.

    Returns None when ready, otherwise a :class:`ProviderReadyState` indicating
    which UI screen the caller should offer (provider or model selection).

    Pure-core helper — no widget/Textual imports.
    """
    act_k = pm.get_active_provider_key() if hasattr(pm, "get_active_provider_key") else ""
    is_connected = pm.is_provider_connected(act_k) if (hasattr(pm, "is_provider_connected") and act_k) else False
    if not is_connected:
        return ProviderReadyState.NEEDS_PROVIDER
    if not getattr(agent, "model", ""):
        return ProviderReadyState.NEEDS_MODEL
    return ProviderReadyState.READY


async def _await_pending_git_restore(agent: Any) -> None:
    """Barrier: wait for a previous rewind's background git restore to finish.

    Snapshotting a checkpoint while an older rewind restore is still rewriting
    the worktree captures (or destroys) mid-restore state. The restore itself is
    never cancelled — its in-flight git calls cannot be interrupted — so the only
    safe order is: finish the restore, then snapshot the new turn.
    """
    task = getattr(agent, "rewind_git_restore_task", None)
    if task is not None and not task.done():
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001 - best-effort barrier, never fatal
            logger.warning("Awaiting pending git checkpoint restore failed: %s", e)


async def _create_git_checkpoint_async(
    canvas: GenCanvas,
    session_id: Optional[str],
    project_path: Optional[str],
) -> None:
    """Persist the session and snapshot a shadow git checkpoint for the newest user message."""
    from core.infrastructure.storage.git_checkpoint import GitCheckpointManager

    try:
        await canvas.save_session()
        if session_id:
            user_msgs = canvas.get_user_messages()
            msg_idx = len(user_msgs) - 1
            if msg_idx >= 0:
                await asyncio.to_thread(
                    GitCheckpointManager.create_checkpoint, session_id, msg_idx, project_path=project_path
                )
    except Exception as e:  # noqa: BLE001 - checkpoint best-effort, never fatal
        logger.warning("Git checkpoint creation failed: %s", e)


async def generate_ai_response(
    agent: Any,
    session: Any,
    canvas: GenCanvas,
    *,
    session_id: Optional[str],
    user_text: str,
    show_in_ui: bool = True,
    attachments: Optional[list] = None,
    project_path: Optional[str] = None,
    display_text: Optional[str] = None,
) -> None:
    """Run the agent stream for a user prompt, recording transcript events and
    driving UI handles via ``canvas``.

    Raises ``asyncio.CancelledError`` (and ``RuntimeError``) outwards to the
    caller so it may run its own teardown (flag reset, session save, queue drain).
    """
    transcript_acc = [""]

    # Prepare the turn: record the user message, render it, snapshot a checkpoint.
    user_event = {"type": "user", "text": user_text, "show_in_ui": show_in_ui}
    if display_text:
        user_event["display_text"] = display_text
    if attachments:
        user_event["attachments_count"] = len(attachments)
    session.add_event(user_event)
    if show_in_ui:
        await canvas.add_user_message(display_text or user_text, attachments)

    await _await_pending_git_restore(agent)
    await _create_git_checkpoint_async(canvas, session_id, project_path)

    thinking_handle: Any = None
    bot_handle: Any = None
    tool_handle: Any = None
    start_time = time.time()

    try:
        # Batch all per-step persistence into one debounced write per turn.
        save_db = _SessionSaveDebounce(canvas.save_session)
        async for step in agent.stream_steps(user_text, attachments=attachments):
            if not step:
                continue
            event_type = step[0]
            val1 = step[1] if len(step) > 1 else ""
            val2 = step[2] if len(step) > 2 else ""
            val3 = step[3] if len(step) > 3 else None
            val4 = step[4] if len(step) > 4 else None

            if event_type == "queued_user_message":
                # Queued prompts are recorded as user msgs, rendered to the UI
                # and given their own git checkpoint.
                q_msg = val1
                q_atts = val2 if val2 else None
                q_show = val3 if val3 is not None else True
                q_display_text = val4 or None
                q_event = {"type": "user", "text": q_msg, "show_in_ui": q_show}
                if q_display_text:
                    q_event["display_text"] = q_display_text
                if q_atts:
                    q_event["attachments_count"] = len(q_atts)
                session.add_event(q_event)
                transcript_acc[0] = ""
                if q_show:
                    # Prefer the short display text (e.g. "/skill-name") over the full
                    # prompt so skills invoked mid-generation render the command in UI.
                    await canvas.add_user_message(q_display_text or q_msg, q_atts)
                    await _await_pending_git_restore(agent)
                    await _create_git_checkpoint_async(canvas, session_id, project_path)
            else:
                record_subagent_step(step, session, transcript_acc)

            if event_type == "thinking_start":
                thinking_handle = await canvas.add_thinking_widget(val1)
            elif event_type == "thinking_delta":
                if thinking_handle:
                    thinking_handle.update_thinking(val1)
            elif event_type == "thinking_end":
                if thinking_handle:
                    try:
                        duration = float(val1)
                        if not math.isfinite(duration):
                            duration = 0.0
                    except Exception:  # noqa: BLE001
                        duration = 0.0
                    thinking_handle.finish_thinking(duration, val2)
                thinking_handle = None
            elif event_type == "tool":
                if bot_handle:
                    bot_handle.flush_pending_stream()
                    content_str = getattr(bot_handle, "content", "")
                    if hasattr(bot_handle, "_stream_parts") and bot_handle._stream_parts:
                        content_str = bot_handle._join_stream_content()
                    if not (content_str or "").strip():
                        bot_handle.remove()
                    else:
                        await bot_handle.finalize_stream()
                bot_handle = None
                targs = val3 if isinstance(val3, dict) else {}
                tool_handle = await canvas.add_tool_call(val1, val2, targs)
                if canvas.register_tool_widget:
                    canvas.register_tool_widget(tool_handle)
            elif event_type == "tool_result":
                if tool_handle:
                    parsed_tool_result = parse_tool_result_step(step)
                    tool_handle.set_result(
                        val1,
                        is_error=parsed_tool_result.is_error,
                        status=parsed_tool_result.status.value
                        if parsed_tool_result.status is not None
                        else None,
                        returncode=parsed_tool_result.returncode,
                    )
                    tool_handle = None
                try:
                    save_db.schedule()
                except Exception:  # noqa: BLE001
                    pass
            elif event_type == "bot_delta":
                if val1:
                    if bot_handle is None:
                        bot_handle = await canvas.add_bot_message()
                    # Stream whitespace deltas too so trailing chars aren't dropped.
                    bot_handle.append_stream_content(val1)
            elif event_type == "bot_reset":
                # Explicit stream reset: drop partial text.
                if bot_handle is not None:
                    try:
                        await bot_handle.reset_stream()
                    except Exception:  # noqa: BLE001
                        pass
            elif event_type == "retry":
                # A retry restarts the reply from scratch: drop partial text.
                if bot_handle is not None:
                    try:
                        await bot_handle.reset_stream()
                    except Exception:  # noqa: BLE001
                        pass
                if canvas.notify:
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
                        canvas.notify(
                            f"{reason}: retrying in {max(1, int(round(delay)))}s (attempt {attempt}/{max_retries})",
                            severity="warning",
                        )
                    except Exception:  # noqa: BLE001
                        pass
            elif event_type in ("bot_text", "outro"):
                if val1.strip():
                    if bot_handle is None:
                        bot_handle = await canvas.add_bot_message()
                    await bot_handle.finalize_stream(val1)
                    bot_handle = None
                try:
                    save_db.schedule()
                except Exception:  # noqa: BLE001
                    pass
            elif event_type == "event_divider":
                div_text = val1 or "Session Compacted"
                await canvas.add_event_divider(div_text)
                canvas.refresh_status_footer()
                try:
                    save_db.schedule()
                except Exception:  # noqa: BLE001
                    pass
    except (asyncio.CancelledError, RuntimeError, KeyboardInterrupt):
        await _handle_interruption(
            agent,
            session,
            canvas,
            thinking_handle,
            bot_handle,
            tool_handle,
            start_time,
        )
        raise
    except Exception as e:  # noqa: BLE001
        canvas.notify(f"Generation failed: {e}", severity="error")
    finally:
        if thinking_handle is not None and getattr(thinking_handle, "is_thinking", False):
            try:
                duration = time.time() - start_time
                thinking_handle.finish_thinking(duration)
            except Exception:  # noqa: BLE001
                pass
        if bot_handle is not None and not getattr(bot_handle, "content", "").strip():
            try:
                bot_handle.remove()
            except Exception:  # noqa: BLE001
                pass
        try:
            await save_db.flush()
        except Exception:  # noqa: BLE001
            pass


async def _handle_interruption(
    agent: Any,
    session: Any,
    canvas: GenCanvas,
    thinking_handle: Any,
    bot_handle: Any,
    tool_handle: Any,
    start_time: float,
) -> None:
    """Clean up partial state after a cancellation/interruption: finish the
    thinking widget, append the partial reply + interruption note to history,
    refresh token accounting and mark any in-flight tool as cancelled."""
    if thinking_handle:
        try:
            duration = time.time() - start_time
            thinking_handle.finish_thinking(duration)
        except Exception:  # noqa: BLE001
            pass
    if bot_handle and getattr(bot_handle, "content", "").strip():
        try:
            await bot_handle.finalize_stream()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(agent, "history"):
        partial = (getattr(bot_handle, "content", "") if bot_handle else "").strip()
        if partial:
            agent.history.append({"role": "assistant", "content": partial})
        agent.history.append({"role": "user", "content": "[System Note: Response interrupted by user]"})
        try:
            from core.infrastructure.runtime.token_util import estimate_tokens

            sys_tok = getattr(agent, "_last_sys_tokens", 0)
            hist_tok = estimate_tokens(agent.history)
            agent.last_context_tokens = sys_tok + hist_tok
            canvas.refresh_status_footer()
        except Exception:  # noqa: BLE001
            pass
    if tool_handle is not None:
        try:
            tool_handle.mark_cancelled()
        except Exception:  # noqa: BLE001
            pass
    if session and hasattr(session, "add_event"):
        if (
            hasattr(session, "messages")
            and session.messages
            and session.messages[-1].get("type") == "tool"
            and "result_text" not in session.messages[-1]
        ):
            try:
                res_text = (
                    getattr(tool_handle, "result_text", "")
                    if tool_handle is not None
                    else ""
                ) or "[Tool call interrupted or cancelled]"
                session.add_event({
                    "type": "tool",
                    "result_text": res_text,
                    "status": "cancelled",
                })
            except Exception:  # noqa: BLE001
                pass
        try:
            session.add_event({"type": "event_divider", "text": "Response Interrupted"})
        except Exception:  # noqa: BLE001
            pass
    try:
        await canvas.add_event_divider("Response Interrupted")
    except Exception:  # noqa: BLE001
        pass
