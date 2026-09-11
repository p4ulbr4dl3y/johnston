import asyncio
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# -- task lookup ------------------------------------------------------------

def _find_task(mgr: Any, task_id: str, kind: str = "shell") -> Any:
    """O(1) task lookup by id via the manager's dict index."""
    if mgr is None:
        return None
    get = getattr(mgr, "get", None)
    if callable(get):
        task = get(task_id)
    else:
        task = next(
            (t for t in mgr if getattr(t, "task_id", None) == task_id),
            None,
        )
    if task is not None and kind and getattr(task, "kind", "") != kind:
        return None
    return task


# -- message index helpers --------------------------------------------------
# Lazy per-session indexes that turn repeated O(n) scans into O(1) lookups.
# Invalidated automatically when len(session.messages) changes (structural
# append/remove).  In-place mutations (result_text, status) don't invalidate
# because they don't shift indices.

_MSG_IDX_LEN = "__idx_len__"

_SESSION_ID_RE = re.compile(
    r"(?:\|\s*id\s+|session[_\s-]?id[:=\s]+)([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)


def _ensure_task_msg_index(session: Any) -> dict[str, int]:
    """Build or return a cached {task_id → message-index} for tool messages."""
    msgs = session.messages
    expected_len = len(msgs)
    cached = getattr(session, "_task_msg_idx", None)
    if isinstance(cached, dict) and cached.get(_MSG_IDX_LEN) == expected_len:
        return cached
    idx: dict[str, int] = {_MSG_IDX_LEN: expected_len}
    for i, msg in enumerate(msgs):
        if not isinstance(msg, dict) or msg.get("type") != "tool":
            continue
        tid = msg.get("task_id") or msg.get("background_task_id")
        if tid and tid not in idx:
            idx[tid] = i
    session._task_msg_idx = idx  # type: ignore[attr-defined]
    return idx


def _find_tool_msg_for_task(session: Any, task_id: str) -> Any:
    """Find a tool message by task_id / background_task_id. O(1) amortized."""
    idx = _ensure_task_msg_index(session)
    pos = idx.get(task_id)
    if pos is None or pos >= len(session.messages):
        return None
    msg = session.messages[pos]
    if isinstance(msg, dict) and msg.get("type") == "tool":
        if msg.get("task_id") == task_id or msg.get("background_task_id") == task_id:
            return msg
    return None


def _ensure_subagent_msg_index(session: Any) -> dict[str, int]:
    """Build or return a cached {session_id → message-index} for invoke_subagent messages."""
    msgs = session.messages
    expected_len = len(msgs)
    cached = getattr(session, "_subagent_msg_idx", None)
    if isinstance(cached, dict) and cached.get(_MSG_IDX_LEN) == expected_len:
        return cached
    idx: dict[str, int] = {_MSG_IDX_LEN: expected_len}
    for i, msg in enumerate(msgs):
        if not isinstance(msg, dict) or msg.get("type") != "tool":
            continue
        if msg.get("tool_type") != "invoke_subagent":
            continue
        sub_id = msg.get("subagent_session_id")
        if sub_id and str(sub_id) not in idx:
            idx[str(sub_id)] = i
        args = msg.get("args")
        if isinstance(args, dict):
            aid = args.get("id") or args.get("session_id")
            if aid and str(aid) not in idx:
                idx[str(aid)] = i
        rtext = msg.get("result_text", "")
        if rtext:
            m = _SESSION_ID_RE.search(str(rtext))
            if m and m.group(1) not in idx:
                idx[m.group(1)] = i
    session._subagent_msg_idx = idx  # type: ignore[attr-defined]
    return idx


def _find_tool_msg_for_subagent(session: Any, session_id: str) -> Any:
    """Find an invoke_subagent tool message by session_id. O(1) amortized."""
    idx = _ensure_subagent_msg_index(session)
    pos = idx.get(session_id)
    if pos is not None and pos < len(session.messages):
        msg = session.messages[pos]
        if isinstance(msg, dict) and msg.get("type") == "tool" and msg.get("tool_type") == "invoke_subagent":
            return msg
    # Fallback: original linear scan for edge cases where the index didn't
    # capture the session_id (e.g. unusual result_text format).
    for msg in session.messages:
        if (
            isinstance(msg, dict)
            and msg.get("type") == "tool"
            and msg.get("tool_type") == "invoke_subagent"
            and (session_id in msg.get("result_text", "") or session_id in str(msg.get("args", {})))
        ):
            return msg
    return None


# -- public API -------------------------------------------------------------

def schedule_session_save(app: Any, session: Any) -> None:
    """Persist a session off the event loop, holding the shared write lock.

    Prefers the app's tracked-task scheduler so writes are awaited; falls back
    to spawning a task on the running loop, or to a direct save when no loop
    is running. Shared by the background-shell and subagent completion paths.
    """
    from johnston.tui.mixins.session_persistence import _global_session_write_lock

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


def update_background_shell_widget(app: Any, task_id: str, result: str, *, task: Any = None) -> None:
    """Repaint the linked shell tool card once a background task finishes."""
    widget = None
    if hasattr(app, "_background_shell_widgets") and isinstance(app._background_shell_widgets, dict):
        widget = app._background_shell_widgets.pop(task_id, None)

    if task is None:
        mgr = getattr(app, "task_manager", None)
        task = _find_task(mgr, task_id, kind="shell")

    task_log = getattr(task, "log_path", None)

    from johnston.tui.adapters import core_bridge

    final_result = core_bridge.truncate_output(
        result or "(no output)",
        max_chars=4000,
        tool_name="shell",
        from_end=True,
        save_log=False,
        log_path=task_log,
    )
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
                msg = _find_tool_msg_for_task(session, task_id)
                if msg is not None:
                    msg["result_text"] = final_result
                    msg["status"] = status
                    msg["task_id"] = task_id
                    msg["background_task_id"] = task_id
                    if task_log:
                        msg["log_path"] = task_log
                schedule_session_save(app, session)
        except Exception as e:
            logger.warning("Failed to update session for background shell %s: %s", task_id, e)


def on_background_shell_completed(app: Any, task_id: str, command_str: str, result: str) -> None:
    """Callback when background shell command finishes."""
    try:
        if not getattr(app, "is_app_active", True):
            return

        mgr = getattr(app, "task_manager", None)
        task = _find_task(mgr, task_id, kind="shell")

        update_background_shell_widget(app, task_id, result, task=task)

        from johnston.tui.adapters import core_bridge

        if getattr(task, "suppress_notification", False):
            return
        task_log = getattr(task, "log_path", None)

        body = core_bridge.truncate_output(
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

        msg = core_bridge.format_background_notification(
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
    finally:
        if hasattr(app, "_background_shell_widgets") and isinstance(app._background_shell_widgets, dict):
            app._background_shell_widgets.pop(task_id, None)


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
        from johnston.tui.adapters import core_bridge

        mgr = getattr(app, "task_manager", None)
        task = _find_task(mgr, task_id, kind="shell")

        if getattr(task, "suppress_notification", False):
            return
        task_log = getattr(task, "log_path", None)

        body = core_bridge.truncate_output(
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

        msg = core_bridge.format_background_notification(
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
                msg = _find_tool_msg_for_subagent(session, session_id)
                if msg is not None:
                    msg["result_text"] = result or "(no output)"
                    msg["status"] = final_status
                    msg["subagent_session_id"] = session_id
                    if isinstance(msg.get("args"), dict):
                        msg["args"]["session_id"] = session_id
                schedule_session_save(app, session)
    except Exception as e:
        logger.warning("Subagent tool completion handling failed: %s", e)
