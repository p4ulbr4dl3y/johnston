"""AI generation orchestration helpers for widgets.

Builds the engine-facing ``GenCanvas`` (pure wiring, no app access) and wraps
the engine call. The event-loop glue (connectivity check, pre/post-stream
footer state, finally teardown, queue drain) stays in the mixin.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from johnston.core.application.generation.engine import (
    GenCanvas,
    NullStreamDriver,
    _await_pending_git_restore,
    _create_git_checkpoint_async,
    _finalize_git_turn_async,
    _handle_interruption,
    _SessionSaveDebounce,
)
from johnston.core.application.session.stream import sync_session_metrics
from johnston.core.client import JohnstonClient
from johnston.core.dto import (
    CompactionEventDTO,
    ContentDeltaDTO,
    ErrorEventDTO,
    QueuedUserMessageDTO,
    RetryEventDTO,
    ThinkingDeltaDTO,
    ToolCallDTO,
    ToolResultDTO,
    TurnCompletedDTO,
)
from johnston.tui.presentation.widgets.chat_stream_driver import ChatStreamDriver

logger = logging.getLogger(__name__)


def build_gen_canvas(
    chat_view: Any,
    *,
    on_tool_widget: Callable[[Any], Any],
    refresh_status_footer: Callable[[], None],
    notify: Callable[..., None],
    save_session: Callable[[], Any],
    cancel_subagents: Optional[Callable[[str], None]] = None,
    driver: Optional[Any] = None,
) -> GenCanvas:
    """Build a GenCanvas bound to the given chat view and app callbacks (no app/self access)."""
    def _add_tool_call(name: str, desc: str, *args: Any, **kwargs: Any) -> Any:
        if args and isinstance(args[0], dict) and "args" not in kwargs:
            return chat_view.add_tool_call(name, desc, args=args[0], **kwargs)
        return chat_view.add_tool_call(name, desc, *args, **kwargs)

    canvas = GenCanvas(
        add_user_message=lambda text, atts: chat_view.add_user_message(text, attachments=atts),
        add_thinking_widget=chat_view.add_thinking_widget,
        add_tool_call=_add_tool_call,
        register_tool_widget=on_tool_widget,
        add_bot_message=chat_view.add_bot_message,
        add_event_divider=chat_view.add_event_divider,
        add_error_message=chat_view.add_error_message,
        get_user_messages=chat_view.get_user_messages,
        get_user_messages_count=getattr(chat_view, "get_total_user_message_count", None),
        refresh_status_footer=refresh_status_footer,
        notify=notify,
        save_session=save_session,
        cancel_subagents=cancel_subagents,
    )
    if driver is None:
        driver = ChatStreamDriver(
            canvas,
            on_tool_widget=on_tool_widget,
            notify=notify,
        )
    canvas.driver = driver
    return canvas


async def run_ai_generation(
    agent: Any,
    session: Any,
    canvas: GenCanvas,
    *,
    session_id: Optional[str],
    user_text: str,
    show_in_ui: bool,
    attachments: Optional[list] = None,
    project_path: Optional[str] = None,
    display_text: Optional[str] = None,
    driver: Optional[Any] = None,
    app: Optional[Any] = None,
    client: Optional[Any] = None,
    checkpoint_manager: Optional[Any] = None,
) -> None:
    """Stream AI generation via app.client.stream, handling StreamEventDTOs.

    CancelledError / generic exceptions propagate to the caller (mixin) which
    owns teardown. Keeps the mixin free of direct engine invocation while
    preserving cancellation semantics.
    """
    user_event = {"type": "user", "text": user_text, "show_in_ui": show_in_ui}
    if display_text:
        user_event["display_text"] = display_text
    if attachments:
        user_event["attachments_count"] = len(attachments)
    if session is not None and hasattr(session, "add_event"):
        session.add_event(user_event)
    if show_in_ui and canvas.add_user_message:
        await canvas.add_user_message(display_text or user_text, attachments)

    await _await_pending_git_restore(agent)
    active_msg_idx = await _create_git_checkpoint_async(
        canvas, session_id, project_path, checkpoint_manager=checkpoint_manager
    )

    if app is None:
        for obj in (agent, canvas):
            if obj is None:
                continue
            if hasattr(obj, "_mock_return_value") or hasattr(obj, "_mock_wraps"):
                if "app" in getattr(obj, "__dict__", {}):
                    app = getattr(obj, "app")
                    break
            else:
                cand = getattr(obj, "app", None)
                if cand is not None:
                    app = cand
                    break

    if client is None and app is not None:
        if hasattr(app, "_mock_return_value") or hasattr(app, "_mock_wraps"):
            if "client" in getattr(app, "__dict__", {}):
                client = getattr(app, "client", None)
        else:
            client = getattr(app, "client", None)

    if client is None:
        pm_cand = getattr(app, "pm", None) if app and not hasattr(getattr(app, "pm", None), "_mock_return_value") else None
        sm_cand = getattr(app, "sm", None) if app and not hasattr(getattr(app, "sm", None), "_mock_return_value") else None
        tm_cand = (
            getattr(app, "task_manager", None)
            if app and not hasattr(getattr(app, "task_manager", None), "_mock_return_value")
            else None
        )
        client = JohnstonClient(
            pm=pm_cand,
            store=sm_cand,
            agent=agent,
            session_id=session_id,
            task_manager=tm_cand,
        )
        if app is not None and not hasattr(app, "_mock_return_value"):
            app.client = client
    else:
        if agent is not None and getattr(client, "agent", None) != agent:
            client.agent = agent
        if session is not None and getattr(client, "session", None) != session:
            client.session = session
        if session_id and getattr(client, "session_id", None) != session_id:
            client.session_id = session_id

    active_driver = driver if driver is not None else getattr(canvas, "driver", None)
    if callable(active_driver) and not hasattr(active_driver, "consume_session_event"):
        active_driver = active_driver(canvas)
    if active_driver is None:
        active_driver = NullStreamDriver()

    save_db = _SessionSaveDebounce(canvas.save_session)
    active_user_event = user_event
    has_tool_calls = False
    start_time = time.time()
    transcript_acc = [""]

    effective_prompt = user_text

    try:
        if app is not None and getattr(app, "client", None) is not None:
            stream_iter = app.client.stream(effective_prompt, attachments=attachments)
        else:
            stream_iter = client.stream(effective_prompt, attachments=attachments)

        async for event in stream_iter:
            if isinstance(event, ContentDeltaDTO):
                if getattr(event, "is_reset", False):
                    transcript_acc[0] = ""
                    if session is not None and hasattr(session, "add_event"):
                        session.add_event({"type": "bot_reset", "from_stream_step": True})
                    await active_driver.consume_session_event(
                        {"type": "bot_reset", "from_stream_step": True},
                        animate=True,
                        is_active=True,
                    )
                else:
                    if getattr(event, "final", False):
                        transcript_acc[0] = event.text
                        bot_evt = {
                            "type": "bot",
                            "text": event.text,
                            "final": True,
                            "from_stream_step": True,
                        }
                    else:
                        transcript_acc[0] += event.text
                        bot_evt = {
                            "type": "bot",
                            "text": transcript_acc[0],
                            "delta": event.text,
                            "from_stream_step": True,
                        }
                    if session is not None and hasattr(session, "add_event"):
                        session.add_event(bot_evt)
                    await active_driver.consume_session_event(
                        bot_evt,
                        animate=True,
                        is_active=True,
                    )

            elif isinstance(event, ThinkingDeltaDTO):
                phase = getattr(event, "phase", "delta")
                dur = getattr(event, "duration", 0.0)
                think_evt: dict[str, Any] = {
                    "type": "thinking",
                    "text": event.thought,
                    "phase": phase,
                    "from_stream_step": True,
                }
                if dur:
                    think_evt["duration"] = dur
                if session is not None and hasattr(session, "add_event"):
                    session.add_event(think_evt)
                await active_driver.consume_session_event(
                    think_evt,
                    animate=True,
                    is_active=True,
                )

            elif isinstance(event, ToolCallDTO):
                status = getattr(event, "status", "running")
                if status == "generating":
                    await active_driver.consume_session_event(
                        {
                            "type": "tool_generating",
                            "tool_type": event.tool_name,
                            "target": getattr(event, "target", ""),
                            "meta": {
                                "id": event.call_id,
                                "index": getattr(event, "index", None),
                            },
                            "from_stream_step": True,
                        },
                        animate=True,
                        is_active=True,
                    )
                elif status == "generating_update":
                    await active_driver.consume_session_event(
                        {
                            "type": "tool_generating_update",
                            "tool_type": event.tool_name,
                            "target": getattr(event, "target", ""),
                            "meta": {
                                "id": event.call_id,
                                "index": getattr(event, "index", None),
                            },
                            "from_stream_step": True,
                        },
                        animate=True,
                        is_active=True,
                    )
                else:
                    has_tool_calls = True
                    target = getattr(event, "target", "")
                    if not target and isinstance(event.args, dict):
                        target = (
                            event.args.get("command")
                            or event.args.get("cmd")
                            or event.args.get("path")
                            or event.args.get("file_path")
                            or event.args.get("target")
                            or ""
                        )
                    tool_evt = {
                        "type": "tool",
                        "tool_type": event.tool_name,
                        "target": str(target),
                        "args": event.args,
                        "tool_id": event.call_id,
                        "from_stream_step": True,
                    }
                    if session is not None and hasattr(session, "add_event"):
                        session.add_event(tool_evt)
                    await active_driver.consume_session_event(
                        tool_evt,
                        animate=True,
                        is_active=True,
                    )

            elif isinstance(event, ToolResultDTO):
                res_evt = {
                    "type": "tool",
                    "tool_type": event.tool_name,
                    "result_text": event.content,
                    "is_error": event.is_error,
                    "status": event.status,
                    "returncode": event.returncode,
                    "from_stream_step": True,
                }
                call_id = getattr(event, "call_id", "")
                if call_id:
                    res_evt["tool_id"] = call_id
                if session is not None and hasattr(session, "add_event"):
                    session.add_event(res_evt)
                await active_driver.consume_session_event(
                    res_evt,
                    animate=True,
                    is_active=True,
                )
                try:
                    save_db.schedule()
                except Exception:
                    pass

            elif isinstance(event, CompactionEventDTO):
                summary = event.summary or "Session Compacted"
                comp_evt = {"type": "event_divider", "text": summary, "from_stream_step": True}
                if session is not None and hasattr(session, "add_event"):
                    session.add_event(comp_evt)
                await active_driver.consume_session_event(
                    comp_evt,
                    animate=True,
                    is_active=True,
                )
                if canvas.refresh_status_footer:
                    canvas.refresh_status_footer()
                try:
                    save_db.schedule()
                except Exception:
                    pass

            elif isinstance(event, TurnCompletedDTO):
                if hasattr(active_driver, "finalize_bot_stream"):
                    await active_driver.finalize_bot_stream()
                if hasattr(active_driver, "finalize_thinking_stream"):
                    active_driver.finalize_thinking_stream(duration=event.duration_s)
                if event.usage and agent is not None:
                    for attr in ("tokens_input", "tokens_output", "total_tokens", "cost_usd"):
                        if attr in event.usage and hasattr(agent, attr):
                            setattr(agent, attr, event.usage[attr])
                if canvas.refresh_status_footer:
                    canvas.refresh_status_footer()
                try:
                    save_db.schedule()
                except Exception:
                    pass

            elif isinstance(event, ErrorEventDTO):
                err_evt = {"type": "error", "text": event.message, "from_stream_step": True}
                if session is not None and hasattr(session, "add_event"):
                    session.add_event(err_evt)
                await active_driver.consume_session_event(
                    err_evt,
                    animate=True,
                    is_active=True,
                )
                if canvas.notify:
                    canvas.notify(f"Generation failed: {event.message}", severity="error")
                if canvas.refresh_status_footer:
                    canvas.refresh_status_footer()
                try:
                    save_db.schedule()
                except Exception:
                    pass

            elif isinstance(event, QueuedUserMessageDTO):
                if has_tool_calls and session_id:
                    await _finalize_git_turn_async(
                        session_id, active_msg_idx, active_user_event, project_path, checkpoint_manager
                    )
                    has_tool_calls = False
                q_event = {"type": "user", "text": event.prompt, "show_in_ui": event.show_in_ui}
                if event.display_text:
                    q_event["display_text"] = event.display_text
                if event.attachments:
                    q_event["attachments_count"] = len(event.attachments)
                if session is not None and hasattr(session, "add_event"):
                    session.add_event(q_event)
                transcript_acc[0] = ""
                active_user_event = q_event
                if event.show_in_ui:
                    if canvas.add_user_message:
                        await canvas.add_user_message(event.display_text or event.prompt, event.attachments)
                    await _await_pending_git_restore(agent)
                    active_msg_idx = await _create_git_checkpoint_async(
                        canvas, session_id, project_path, checkpoint_manager=checkpoint_manager
                    )

            elif isinstance(event, RetryEventDTO):
                await active_driver.consume_session_event(
                    {
                        "type": "retry",
                        "attempt": event.attempt,
                        "max_retries": event.max_retries,
                        "delay": event.delay,
                        "error": event.error,
                        "from_stream_step": True,
                    },
                    animate=True,
                    is_active=True,
                )

    except (asyncio.CancelledError, RuntimeError, KeyboardInterrupt):
        await _handle_interruption(
            agent,
            session,
            canvas,
            getattr(active_driver, "thinking_handle", None),
            getattr(active_driver, "bot_handle", None),
            start_time=start_time,
            tool_handles=getattr(active_driver, "tool_handles", None),
        )
        if hasattr(active_driver, "thinking_handle"):
            active_driver.thinking_handle = None
        raise
    except Exception as e:
        logger.exception("AI generation failed: %s", e)
        if canvas.notify:
            canvas.notify(f"Generation failed: {e}", severity="error")
        if hasattr(active_driver, "cleanup_unfinalized_tools"):
            try:
                active_driver.cleanup_unfinalized_tools(f"Error: {e}")
            except Exception:
                pass
    finally:
        if hasattr(active_driver, "cleanup_unfinalized_tools"):
            try:
                active_driver.cleanup_unfinalized_tools()
            except Exception:
                pass
        thinking_handle = getattr(active_driver, "thinking_handle", None)
        if thinking_handle is not None and getattr(thinking_handle, "is_thinking", False):
            try:
                duration = time.time() - start_time
                thinking_handle.finish_thinking(duration)
            except Exception:
                pass
        bot_handle = getattr(active_driver, "bot_handle", None)
        if bot_handle is not None and not getattr(bot_handle, "content", "").strip():
            try:
                bot_handle.remove()
            except Exception:
                pass
        if has_tool_calls and session_id:
            await _finalize_git_turn_async(
                session_id, active_msg_idx, active_user_event, project_path, checkpoint_manager
            )
        try:
            sync_session_metrics(session, agent)
        except Exception:
            pass
        try:
            await save_db.flush()
        except Exception:
            pass
