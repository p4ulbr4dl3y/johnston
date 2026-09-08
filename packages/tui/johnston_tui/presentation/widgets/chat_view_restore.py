"""Restore a saved transcript event dict into a rendered ChatView widget."""
import sys
from typing import Any

from johnston_core.domain.policies.messages import is_ui_visible_user_message
from johnston_core.infrastructure.config.settings import get_settings

__all__ = ["restore_message_item", "resolve_restore_message_item", "resolve_settings"]


async def restore_message_item(
    chat_view: Any,
    msg: dict,
    before: Any = None,
    task_manager: Any = None,
) -> Any:
    """Restore a saved transcript event dict into a rendered ChatView widget."""
    if not isinstance(msg, dict):
        return None
    mtype = msg.get("type")
    kw = {"before": before} if before is not None else {}
    if mtype == "user":
        if not is_ui_visible_user_message(msg):
            return None
        text = msg.get("display_text") or msg.get("text", "")
        att_count = msg.get("attachments_count", 0)
        if not att_count and msg.get("attachments"):
            att_count = len(msg.get("attachments"))
        return await chat_view.add_user_message(
            text,
            animate=False,
            attachments_count=att_count,
            **kw,
        )
    elif mtype == "bot":
        text = msg.get("text", "")
        if not text.strip():
            return None
        bm = await chat_view.add_bot_message(animate=False, **kw)
        if hasattr(bm, "set_final_content"):
            await bm.set_final_content(text)
        return bm
    elif mtype == "thinking":
        dur = msg.get("duration", 0.0)
        txt = msg.get("text", "")
        tw = await chat_view.add_thinking_widget(animate=False, is_active=False, **kw)
        if hasattr(tw, "finish_thinking"):
            tw.finish_thinking(dur, txt)
        return tw
    elif mtype == "tool":
        ttype = msg.get("tool_type", "")
        target = msg.get("target", "")
        rtext = msg.get("result_text", "")
        targs = msg.get("args", {})
        status = msg.get("status")
        if not ttype and not target and not targs and status == "cancelled":
            return None
        task_id = msg.get("task_id") or msg.get("background_task_id")
        if status == "running":
            mgr = task_manager
            is_live = bool(task_id and mgr is not None and getattr(mgr, "_tasks", {}).get(task_id) is not None)
            if not is_live:
                status = "done" if rtext else "cancelled"
        sub_id = msg.get("subagent_session_id") or (
            (targs.get("id") or targs.get("session_id")) if isinstance(targs, dict) else None
        )
        if not sub_id and ttype in ("invoke_subagent", "message_subagent"):
            title = targs.get("title") or targs.get("prompt")
            if title:
                app = None
                try:
                    app = chat_view.app
                except Exception:
                    pass
                store = getattr(app, "sm", None) if app else None
                if store is None:
                    try:
                        from johnston_core.infrastructure.storage.session_store import SessionStore

                        store = SessionStore.get_instance()
                    except Exception:
                        store = None
                if store is not None and hasattr(store, "find_session_by_title_or_id"):
                    try:
                        curr_sid = getattr(app, "current_session_id", None) if app else None
                        found = store.find_session_by_title_or_id(str(title), parent_id=curr_sid)
                        if not found:
                            found = store.find_session_by_title_or_id(str(title))
                        if found and getattr(found, "id", None):
                            sub_id = str(found.id)
                            f_status = getattr(found, "status", None)
                            if status in ("running", "cancelled") and f_status in (
                                "error",
                                "cancelled",
                                "done",
                                "completed",
                            ):
                                status = (
                                    "error"
                                    if f_status == "error"
                                    else ("cancelled" if f_status == "cancelled" else "done")
                                )
                    except Exception:
                        pass

        widget = await chat_view.add_tool_call(
            ttype,
            target,
            result_text=rtext,
            args=targs,
            status=status,
            returncode=msg.get("returncode"),
            animate=False,
            subagent_session_id=str(sub_id) if sub_id is not None else None,
            background_task_id=task_id,
            log_path=msg.get("log_path"),
            **kw,
        )
        return widget
    elif mtype == "event_divider":
        ctxt = msg.get("text", "Session Compacted")
        return await chat_view.add_event_divider(ctxt, animate=False, **kw)
    elif mtype == "error":
        ctxt = msg.get("text", "")
        return await chat_view.add_error_message(ctxt, animate=False, **kw)
    return None


def resolve_restore_message_item() -> Any:
    """Resolve the active restore_message_item function.

    Checks ``chat_container`` for a runtime-injected override before falling
    back to the module-level ``restore_message_item`` defined here.
    """
    mod = sys.modules.get("johnston_tui.presentation.widgets.chat_container")
    if mod is not None and hasattr(mod, "restore_message_item"):
        return getattr(mod, "restore_message_item")
    return restore_message_item


def resolve_settings() -> Any:
    """Resolve the active settings object.

    Checks ``chat_container`` for a runtime-injected ``get_settings`` override
    before falling back to the canonical ``core.infrastructure.config.settings.get_settings``.
    """
    mod = sys.modules.get("johnston_tui.presentation.widgets.chat_container")
    if mod is not None and hasattr(mod, "get_settings"):
        return getattr(mod, "get_settings")()
    return get_settings()
