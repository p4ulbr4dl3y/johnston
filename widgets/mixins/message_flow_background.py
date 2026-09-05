import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def schedule_session_save(app: Any, session: Any) -> None:
    """Persist a session off the event loop, holding the shared write lock.

    Prefers the app's tracked-task scheduler so writes are awaited; falls back
    to spawning a task on the running loop, or to a direct save when no loop
    is running. Shared by the background-shell and subagent completion paths.
    """
    from widgets.mixins.session_persistence import _global_session_write_lock

    def _save_locked(s: Any) -> None:
        with _global_session_write_lock:
            app.sm.save(s)

    save_coro = asyncio.to_thread(_save_locked, session)
    if hasattr(app, "create_tracked_task") and callable(app.create_tracked_task):
        app.create_tracked_task(save_coro)
    else:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(save_coro)
        except RuntimeError:
            _save_locked(session)


def update_background_shell_widget(app: Any, task_id: str, result: str) -> None:
    """Repaint the linked shell tool card once a background task finishes."""
    mgr = getattr(app, "task_manager", None)
    task = None
    if mgr is not None:
        task = next(
            (t for t in mgr if getattr(t, "task_id", None) == task_id and getattr(t, "kind", "") == "shell"),
            None,
        )
    task_log = getattr(task, "log_path", None)

    from tools.base import truncate_output

    final_result = truncate_output(
        result or "(no output)",
        max_chars=4000,
        tool_name="shell",
        from_end=True,
        save_log=False,
        log_path=task_log,
    )
    reg = getattr(app, "_background_shell_widgets", None)
    widget = (reg or {}).pop(task_id, None)
    task_status = (getattr(getattr(task, "status", None), "value", None) or "").lower() if task is not None else ""
    status = "error" if task_status == "error" else ("done" if task_status in ("completed", "killed", "timeout") else "done")

    if widget is not None:
        try:
            widget.set_result(final_result, status=status)
        except Exception as e:
            logger.warning("Background shell widget update failed: %s", e)

    sid = getattr(app, "current_session_id", None)
    if sid and hasattr(app, "sm"):
        try:
            session = app.sm.get(sid, reload=False)
            if session:
                for msg in session.messages:
                    if isinstance(msg, dict) and msg.get("type") == "tool" and task_id in msg.get("result_text", ""):
                        msg["result_text"] = final_result
                        msg["status"] = status
                        break
                schedule_session_save(app, session)
        except Exception as e:
            logger.warning("Failed to update session for background shell %s: %s", task_id, e)


def on_background_shell_completed(app: Any, task_id: str, command_str: str, result: str) -> None:
    """Callback when background shell command finishes."""
    if not getattr(app, "is_app_active", True):
        return
    try:
        update_background_shell_widget(app, task_id, result)
        from tools.base import format_background_notification, truncate_output

        mgr = getattr(app, "task_manager", None)
        task = None
        if mgr is not None:
            task = next(
                (t for t in mgr if getattr(t, "task_id", None) == task_id and getattr(t, "kind", "") == "shell"),
                None,
            )
        if getattr(task, "suppress_notification", False):
            return
        task_log = getattr(task, "log_path", None)

        body = truncate_output(
            result,
            max_chars=4000,
            tool_name="shell",
            from_end=True,
            save_log=False,
            log_path=task_log,
        )

        task_status = getattr(task, "status", None)
        status_val = task_status.value if hasattr(task_status, "value") else ""
        exit_code = getattr(task, "exit_code", None)
        notif_status = "completed"
        if getattr(task, "timed_out", False):
            notif_status = "error"
            hard_to = getattr(task, "hard_timeout", "")
            state_hint = f"[status: error | timed out after {hard_to}s]"
            body = f"{state_hint}\n{body}"
        else:
            if status_val == "error":
                notif_status = "error"
            elif status_val in ("killed", "cancelled"):
                notif_status = "cancelled"
            elif exit_code not in (None, 0):
                notif_status = "error"

            if notif_status in ("error", "cancelled") or (exit_code not in (None, 0)):
                state_hint = (
                    f"[exit code: {exit_code}]" if exit_code is not None else f"[status: {notif_status}]"
                )
                body = f"{state_hint}\n{body}"

        msg = format_background_notification(
            "shell",
            command_str,
            task_id,
            body,
            status=notif_status,
            truncated=len(result) > 4000,
        )
        target_sid = getattr(task, "session_id", None) or getattr(app, "current_session_id", None)
        curr_sid = getattr(app, "current_session_id", None)
        if app.is_generating or (target_sid and curr_sid and target_sid != curr_sid):
            app.message_queue.append((msg, False, None, target_sid))
        else:
            app.generate_ai_response(msg, show_in_ui=False)
    except Exception as e:
        logger.warning("Background completion handling failed: %s", e)


def on_background_shell_progress(
    app: Any,
    task_id: str,
    command_str: str,
    result: str,
    *,
    event: str = "inactivity",
    idle_seconds: Optional[int] = None,
) -> None:
    """Callback when background shell emits a progress notification (e.g. inactivity)."""
    if not getattr(app, "is_app_active", True):
        return
    try:
        from tools.base import format_background_notification, truncate_output

        mgr = getattr(app, "task_manager", None)
        task = None
        if mgr is not None:
            task = next(
                (t for t in mgr if getattr(t, "task_id", None) == task_id and getattr(t, "kind", "") == "shell"),
                None,
            )
        if getattr(task, "suppress_notification", False):
            return
        task_log = getattr(task, "log_path", None)

        body = truncate_output(
            result,
            max_chars=4000,
            tool_name="shell",
            from_end=True,
            save_log=False,
            log_path=task_log,
        )
        hint = (
            f"[process running with no output for {idle_seconds}s]"
            if idle_seconds is not None
            else "[process still running]"
        )
        body = f"{hint}\n{body}"

        msg = format_background_notification(
            "shell",
            command_str,
            task_id,
            body,
            status="running",
            event=event,
            idle_seconds=idle_seconds,
            truncated=len(result) > 4000,
        )
        target_sid = getattr(task, "session_id", None) or getattr(app, "current_session_id", None)
        curr_sid = getattr(app, "current_session_id", None)
        if app.is_generating or (target_sid and curr_sid and target_sid != curr_sid):
            app.message_queue.append((msg, False, None, target_sid))
        else:
            app.generate_ai_response(msg, show_in_ui=False)
    except Exception as e:
        logger.warning("Background progress handling failed: %s", e)


def on_subagent_tool_completed(app: Any, session_id: str, status: str, result: str = "") -> None:
    """Callback when a background subagent finishes."""
    if not getattr(app, "is_app_active", True):
        return
    try:
        reg = getattr(app, "_subagent_tools", None)
        widget = reg.pop(session_id, None) if isinstance(reg, dict) else None
        status_clean = (status or "").lower()
        if widget is not None:
            if status_clean == "cancelled":
                widget.mark_cancelled()
            elif status_clean == "error":
                widget.set_result(result or "(no output)", status="error")
            else:
                widget.set_result(result or "(no output)", status="done")

        final_status = "error" if status_clean == "error" else ("cancelled" if status_clean == "cancelled" else "done")
        sid = getattr(app, "current_session_id", None)
        if sid and hasattr(app, "sm"):
            session = app.sm.get(sid, reload=False)
            if session:
                for msg in session.messages:
                    if isinstance(msg, dict) and msg.get("type") == "tool" and msg.get("tool_type") == "invoke_subagent":
                        if session_id in msg.get("result_text", "") or session_id in str(msg.get("args", {})):
                            msg["result_text"] = result or "(no output)"
                            msg["status"] = final_status
                            break
                schedule_session_save(app, session)
    except Exception as e:
        logger.warning("Subagent tool completion handling failed: %s", e)
