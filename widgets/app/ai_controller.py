"""AI generation orchestration helpers for widgets.

Builds the engine-facing ``GenCanvas`` (pure wiring, no app access) and wraps
the engine call. The event-loop glue (connectivity check, pre/post-stream
footer state, finally teardown, queue drain) stays in the mixin.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.application.generation.ai_generator import GenCanvas
from core.application.generation.ai_generator import generate_ai_response as _engine


def build_gen_canvas(
    chat_view: Any,
    *,
    on_tool_widget: Callable[[Any], Any],
    refresh_status_footer: Callable[[], None],
    notify: Callable[..., None],
    save_session: Callable[[], Any],
) -> GenCanvas:
    """Build a GenCanvas bound to the given chat view and app callbacks (no app/self access)."""
    return GenCanvas(
        add_user_message=lambda text, atts: chat_view.add_user_message(text, attachments=atts),
        add_thinking_widget=chat_view.add_thinking_widget,
        add_tool_call=lambda name, desc, args: chat_view.add_tool_call(name, desc, args=args),
        register_tool_widget=on_tool_widget,
        add_bot_message=chat_view.add_bot_message,
        add_event_divider=chat_view.add_event_divider,
        get_user_messages=chat_view.get_user_messages,
        get_user_messages_count=getattr(chat_view, "get_total_user_message_count", None),
        refresh_status_footer=refresh_status_footer,
        notify=notify,
        save_session=save_session,
    )


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
) -> None:
    """Thin wrapper over the generation engine, forwarding the call unchanged.

    CancelledError / generic exceptions propagate to the caller (mixin) which
    owns teardown. Keeps the mixin free of direct engine invocation while
    preserving cancellation semantics.
    """
    await _engine(
        agent,
        session,
        canvas,
        session_id=session_id,
        user_text=user_text,
        show_in_ui=show_in_ui,
        attachments=attachments,
        project_path=project_path,
        display_text=display_text,
    )
