import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def exec_shell_command(app: Any, cmd: str, user_text: Optional[str] = None) -> None:
    """Execute a user shell command (!cmd) directly without calling LLM."""
    try:
        from johnston.tui.chat_input import ChatInput

        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
    except Exception:
        pass

    if hasattr(app, "_apply_pending_fork_or_readonly"):
        app._apply_pending_fork_or_readonly()

    full_prompt = user_text or f"!{cmd}"
    from johnston.tui.presentation.widgets.chat_container import ChatView

    chat_view = app.query_one(ChatView)
    if hasattr(chat_view, "clear_welcome"):
        chat_view.clear_welcome()

    # Mount user message in UI
    await chat_view.add_user_message(full_prompt)

    # Record user event to active session
    session = None
    if hasattr(app, "sm") and hasattr(app, "current_session_id") and app.current_session_id:
        session = app.sm.get(app.current_session_id, reload=False) or app.sm.create_main(app.current_session_id)
    elif hasattr(app, "session"):
        session = app.session

    if session is not None and hasattr(session, "add_event"):
        session.add_event({"type": "user", "text": full_prompt})
        if hasattr(app, "save_current_session_async"):
            await app.save_current_session_async(force=True)
        elif hasattr(app, "save_current_session"):
            app.save_current_session()

    # Mount running tool call widget
    tool_widget = await chat_view.add_tool_call(
        tool_type="shell",
        target=cmd,
        args={"command": cmd},
        status="running",
    )

    from johnston.core.tools.context import ToolContext
    from johnston.core.tools.shell import ShellTool

    ctx = ToolContext(app)
    tool = ShellTool()
    app.current_tool_widget = tool_widget
    try:
        res = await tool.execute({"command": cmd}, ctx=ctx)
        content = res.content or ""
        returncode = getattr(res, "returncode", None)
        is_error = getattr(res, "is_error", False) or (returncode is not None and returncode != 0)
        res_status = getattr(res, "status", None)
        if hasattr(res_status, "value"):
            status = res_status.value
        elif isinstance(res_status, str):
            status = res_status
        else:
            status = "error" if is_error else "done"
    except Exception as e:
        content = f"ERR: {e}"
        returncode = 1
        is_error = True
        status = "error"
    finally:
        app.current_tool_widget = None

    if tool_widget is not None:
        tool_widget.set_result(content, is_error=is_error, status=status, returncode=returncode)
        if hasattr(tool_widget, "render_header"):
            tool_widget.render_header()
        if hasattr(tool_widget, "render_content"):
            tool_widget.render_content()

    if session is not None and hasattr(session, "add_event"):
        session.add_event({
            "type": "tool",
            "tool_type": "shell",
            "target": cmd,
            "result_text": content,
            "args": {"command": cmd},
            "status": status,
            "returncode": returncode,
        })

    agent = getattr(app, "agent", None)
    if agent is not None and hasattr(agent, "history") and isinstance(agent.history, list):
        history_text = f"! {cmd}\n\n{content}".rstrip() if content else f"! {cmd}"
        agent.history.append({"role": "user", "content": history_text})

    if hasattr(app, "save_current_session_async"):
        await app.save_current_session_async(force=True)
    elif hasattr(app, "save_current_session"):
        app.save_current_session()

    if getattr(app, "is_app_active", True) and not getattr(app, "is_generating", False):
        next_item = (
            app._pop_queued_for_current_session() if hasattr(app, "_pop_queued_for_current_session") else None
        )
        if next_item is not None:
            kw = {}
            if len(next_item) > 4 and next_item[4]:
                kw["display_text"] = next_item[4]
            asyncio.create_task(
                app._process_queued_message(
                    next_item[0],
                    next_item[1],
                    next_item[2],
                    **kw,
                )
            )
