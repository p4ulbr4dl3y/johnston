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
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from core.application.session.stream import record_session_step
from core.domain.defaults.errors import parse_stream_step
from core.domain.entities.session import record_session_interruption
from core.domain.policies.messages import (
    SYSTEM_NOTICE_KIND_INTERRUPTED,
    format_system_note,
)
from core.domain.ports.checkpoint import get_checkpoint_manager
from widgets.presentation.widgets.chat_stream_driver import ChatStreamDriver

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
    add_error_message: Callable[[str], Any] = field(default=None)
    get_user_messages: Callable[[], Any] = field(default=None)
    get_user_messages_count: Optional[Callable[[], int]] = field(default=None)
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
    project_path: Optional[str] = None,
    checkpoint_manager: Optional[Any] = None,
) -> int:
    cm = checkpoint_manager or get_checkpoint_manager()
    msg_idx = -1
    try:
        await canvas.save_session()
        if session_id and cm:
            if getattr(canvas, "get_user_messages_count", None) is not None and callable(canvas.get_user_messages_count):
                user_count = canvas.get_user_messages_count()
            else:
                user_msgs = canvas.get_user_messages() if canvas.get_user_messages else []
                user_count = len(user_msgs)
            msg_idx = user_count - 1
            if msg_idx >= 0:
                await asyncio.to_thread(
                    cm.create_checkpoint, session_id, msg_idx, project_path=project_path
                )
    except Exception as e:  # noqa: BLE001 - checkpoint best-effort, never fatal
        logger.warning("Git checkpoint creation failed: %s", e)
    return msg_idx


async def _finalize_git_turn_async(
    session_id: Optional[str],
    msg_idx: int,
    user_event: dict,
    project_path: Optional[str] = None,
    checkpoint_manager: Optional[Any] = None,
) -> None:
    if not session_id or msg_idx < 0:
        return
    cm = checkpoint_manager or get_checkpoint_manager()
    if not cm or not hasattr(cm, "finalize_turn"):
        return
    try:
        touched = await asyncio.to_thread(cm.finalize_turn, session_id, msg_idx, project_path=project_path)
        user_event["touched_files"] = touched
    except Exception as e:  # noqa: BLE001
        logger.warning("Git checkpoint turn finalization failed: %s", e)


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
    checkpoint_manager: Optional[Any] = None,
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
    if checkpoint_manager is not None:
        active_msg_idx = await _create_git_checkpoint_async(
            canvas, session_id, project_path, checkpoint_manager=checkpoint_manager
        )
    else:
        active_msg_idx = await _create_git_checkpoint_async(canvas, session_id, project_path)

    active_user_event = user_event
    has_tool_calls = False
    start_time = time.time()
    driver = ChatStreamDriver(
        canvas,
        on_tool_widget=canvas.register_tool_widget,
        notify=canvas.notify,
    )

    try:
        # Batch all per-step persistence into one debounced write per turn.
        save_db = _SessionSaveDebounce(canvas.save_session)
        async for step in agent.stream_steps(user_text, attachments=attachments):
            parsed = parse_stream_step(step)
            if parsed is None:
                continue
            event_type = parsed.event_type
            val1 = parsed.val1
            val2 = parsed.val2
            val3 = parsed.val3
            val4 = parsed.val4

            if event_type == "queued_user_message":
                if has_tool_calls and session_id:
                    await _finalize_git_turn_async(
                        session_id, active_msg_idx, active_user_event, project_path, checkpoint_manager
                    )
                    has_tool_calls = False
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
                active_user_event = q_event
                if q_show:
                    # Prefer the short display text (e.g. "/skill-name") over the full
                    # prompt so skills invoked mid-generation render the command in UI.
                    await canvas.add_user_message(q_display_text or q_msg, q_atts)
                    await _await_pending_git_restore(agent)
                    active_msg_idx = await _create_git_checkpoint_async(
                        canvas, session_id, project_path, checkpoint_manager=checkpoint_manager
                    )
            else:
                record_session_step(step, session, transcript_acc)

            await driver.consume_stream_step(step)

            if event_type == "tool":
                has_tool_calls = True
            elif event_type in ("tool_result", "bot_text", "outro"):
                try:
                    save_db.schedule()
                except Exception:  # noqa: BLE001
                    pass
            elif event_type in ("error", "event_divider"):
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
            driver.thinking_handle,
            driver.bot_handle,
            start_time=start_time,
            tool_handles=driver.tool_handles,
        )
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("AI generation failed: %s", e)
        canvas.notify(f"Generation failed: {e}", severity="error")
        if hasattr(driver, "cleanup_unfinalized_tools"):
            try:
                driver.cleanup_unfinalized_tools(f"Error: {e}")
            except Exception:  # noqa: BLE001
                pass
    finally:
        if hasattr(driver, "cleanup_unfinalized_tools"):
            try:
                driver.cleanup_unfinalized_tools()
            except Exception:  # noqa: BLE001
                pass
        if driver.thinking_handle is not None and getattr(driver.thinking_handle, "is_thinking", False):
            try:
                duration = time.time() - start_time
                driver.thinking_handle.finish_thinking(duration)
            except Exception:  # noqa: BLE001
                pass
        if driver.bot_handle is not None and not getattr(driver.bot_handle, "content", "").strip():
            try:
                driver.bot_handle.remove()
            except Exception:  # noqa: BLE001
                pass
        if has_tool_calls and session_id:
            await _finalize_git_turn_async(
                session_id, active_msg_idx, active_user_event, project_path, checkpoint_manager
            )
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
    tool_handle: Any = None,
    start_time: float = 0.0,
    tool_handles: Any = None,
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
        # Structured interruption note. The model sees a typed signal with
        # phase info (streaming/bot) so it knows the previous turn was cut
        # short and can decide whether to retry, summarize, or ask the user.
        # Body deliberately empty — the kind attribute carries the meaning;
        # filling the body would be redundant and risks injection of partial
        # tool output that the model would otherwise re-execute.
        phase = "bot" if partial else "streaming"
        note = format_system_note(
            kind=SYSTEM_NOTICE_KIND_INTERRUPTED,
            body="",
            phase=phase,
        )
        agent.history.append({"role": "user", "content": note})
        try:
            from core.infrastructure.runtime.token_util import estimate_tokens

            sys_tok = getattr(agent, "_last_sys_tokens", 0)
            hist_tok = estimate_tokens(agent.history)
            agent.last_context_tokens = sys_tok + hist_tok
            canvas.refresh_status_footer()
        except Exception:  # noqa: BLE001
            pass
    active_handles = tool_handles if tool_handles is not None else tool_handle
    if isinstance(active_handles, deque):
        handles_to_cancel = []
        while active_handles:
            handles_to_cancel.append(active_handles.popleft())
    elif isinstance(active_handles, list):
        handles_to_cancel = list(active_handles)
        active_handles.clear()
    elif active_handles:
        handles_to_cancel = [active_handles]
    else:
        handles_to_cancel = []
    for h in handles_to_cancel:
        try:
            if getattr(h, "status", None) == "generating":
                if hasattr(h, "remove"):
                    h.remove()
                else:
                    h.mark_cancelled()
            else:
                h.mark_cancelled()
        except Exception:  # noqa: BLE001
            pass
    record_session_interruption(session, "Response Interrupted")
    try:
        await canvas.add_event_divider("Response Interrupted")
    except Exception:  # noqa: BLE001
        pass
