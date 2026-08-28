"""Session-related slash commands (new, resume, compact, rewind, fork, rename, diff)."""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from core.application.session.actions import (
    compact_session,
    get_rewind_git_stats,
    new_session,
    rewind_session,
)
from widgets.chat_input import ChatInput
from widgets.presentation.commands.base import BaseCommand
from widgets.presentation.commands.helpers import (
    cancel_active_workers,
    cancel_active_workers_and_tasks,
    reset_app_state,
)
from widgets.presentation.screens.constants import MESSAGE_INPUT
from widgets.presentation.screens.diff import DiffScreen
from widgets.presentation.screens.fork import FORK_CURRENT_STATE, ForkScreen
from widgets.presentation.screens.rename_session import RenameSessionScreen
from widgets.presentation.screens.resume import ResumeScreen
from widgets.presentation.screens.rewind import RewindScreen, RewindSelection
from widgets.presentation.widgets.chat_container import ChatView


def _get_cmd_attr(name: str, fallback: Any) -> Any:
    mod = sys.modules.get("widgets.commands")
    return getattr(mod, name, fallback) if mod else fallback


class NewCommand(BaseCommand):
    name = "/new"
    aliases = ["/clear", "/reset"]
    description = "Start a new chat session"

    async def execute(self, app) -> None:
        def cancel_workers():
            for w in [w for w in getattr(app, "workers", []) if w.is_running]:
                w.cancel()

        async def kill_all_tasks():
            await app.task_manager.kill_all()

        def cancel_subagents():
            from core.application.session.stream import cancel_running_subagents

            cancel_running_subagents(app.sm)

        old_id = getattr(app, "current_session_id", None)
        if old_id and hasattr(app.sm, "release_session_lock"):
            app.sm.release_session_lock(old_id)

        new_sess_fn = _get_cmd_attr("new_session", new_session)
        new_id = await new_sess_fn(
            app.sm,
            app.agent,
            cancel_workers=cancel_workers,
            kill_all_tasks=kill_all_tasks,
            cancel_subagents=cancel_subagents,
        )

        if hasattr(app.sm, "acquire_session_lock"):
            app.sm.acquire_session_lock(new_id)

        role = getattr(app.agent, "role", "worker") if app.agent else "worker"
        reset_app_state(app, is_generating=False, is_read_only=False, clear_queue=True, session_id=new_id, role=role)

        chat_view = app.query_one(ChatView)
        await chat_view.remove_children()
        chat_view.check_welcome()
        app.refresh_status_footer()


class ResumeCommand(BaseCommand):
    name = "/resume"
    aliases = ["/sessions", "/continue", "/load"]
    description = "Resume a saved session"

    async def execute(self, app) -> None:
        sessions = await asyncio.to_thread(app.sm.list_main_sessions)
        if not sessions:
            app.notify("No saved sessions in this project", severity="warning")
            return

        def _apply_selected(sid: str, read_only: bool = False) -> None:
            cancel_active_workers(app)
            reset_app_state(app, is_generating=False, clear_queue=True)
            if read_only:
                app.load_session_ui(sid, read_only=True)
            else:
                app.load_session_ui(sid)
            app.query_one(MESSAGE_INPUT, ChatInput).focus()

        def on_resume_selected(result: str | None) -> None:
            if not result:
                app.query_one(MESSAGE_INPUT, ChatInput).focus()
                return

            if ":" in result and (result.startswith("steal:") or result.startswith("readonly:")):
                choice, sid = result.split(":", 1)
                if choice == "steal":
                    if hasattr(app, "sm"):
                        app.sm.steal_session_lock(sid)
                    _apply_selected(sid)
                elif choice == "readonly":
                    _apply_selected(sid, read_only=True)
                return

            _apply_selected(result)

        curr_sid = getattr(app, "current_session_id", None)
        app.push_screen(ResumeScreen(sessions, current_session_id=curr_sid), callback=on_resume_selected)


class CompactCommand(BaseCommand):
    name = "/compact"
    aliases = ["/compress", "/summarize", "/smol"]
    description = "Compact session conversation history"

    async def execute(self, app) -> None:
        if not hasattr(app, "agent") or not app.agent:
            app.notify("No active agent found", severity="error")
            return

        divider = None

        if hasattr(app, "query_one"):
            try:
                cv = app.query_one(ChatView)
                if cv and hasattr(cv, "add_event_divider"):
                    divider = await cv.add_event_divider("Compacting session...")
            except Exception:
                pass

        def save_cb() -> None:
            if hasattr(app, "save_current_session"):
                try:
                    app.save_current_session()
                except Exception:
                    pass

        def on_begin() -> None:
            app.is_generating = True

        def on_divider_update(title: str) -> None:
            nonlocal divider
            if divider and hasattr(divider, "update_title"):
                divider.update_title(title)

        try:
            compact_fn = _get_cmd_attr("compact_session", compact_session)
            outcome = await compact_fn(
                app.agent,
                save_session_cb=save_cb,
                on_begin=on_begin,
                on_divider_update=on_divider_update,
                refresh_footer_cb=lambda: app.refresh_status_footer(),
            )
            if outcome.success:
                try:
                    if hasattr(app, "sm") and hasattr(app, "current_session_id") and app.current_session_id:
                        sess = app.sm.get(app.current_session_id, reload=False)
                        if sess:
                            sess.add_event({"type": "event_divider", "text": outcome.title or "Session Compacted"})
                except Exception:
                    pass
            else:
                app.notify(outcome.message or "Context compaction failed", severity="warning")
        finally:
            app.is_generating = False
            if hasattr(app, "_pop_queued_for_current_session") and hasattr(app, "_process_queued_message"):
                next_item = app._pop_queued_for_current_session()
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
            elif getattr(app, "message_queue", None):
                next_item = app.message_queue.pop(0)
                prompt = next_item[0]
                show_in_ui = next_item[1] if len(next_item) > 1 else True
                kwargs = {"attachments": next_item[2]} if len(next_item) > 2 else {}
                if len(next_item) > 4 and next_item[4]:
                    kwargs["display_text"] = next_item[4]
                if hasattr(app, "trigger_ai_response"):
                    app.trigger_ai_response(prompt, show_in_ui=show_in_ui, **kwargs)


class RewindCommand(BaseCommand):
    name = "/rewind"
    aliases = ["/undo", "/history"]
    description = "Rollback chat history to a message"

    async def execute(self, app) -> None:
        chat_view = app.query_one(ChatView)
        if hasattr(chat_view, "load_all_older_messages") and callable(chat_view.load_all_older_messages):
            res = chat_view.load_all_older_messages()
            if asyncio.iscoroutine(res):
                await res
        user_msgs = chat_view.get_user_messages()
        if not user_msgs:
            app.notify("History is empty: no messages to rollback", severity="warning")
            return

        curr_sid = getattr(app, "current_session_id", None)
        proj_path = getattr(app.sm, "project_path", None) if hasattr(app, "sm") else None
        sm = getattr(app, "sm", None)
        session = sm.get(curr_sid, reload=False) if (sm and curr_sid) else None
        get_stats_fn = _get_cmd_attr("get_rewind_git_stats", get_rewind_git_stats)
        msgs_with_stats = await get_stats_fn(curr_sid, user_msgs, proj_path, session=session)
        checkpoints_enabled = any(m.git_stats for m in msgs_with_stats)

        async def on_rewind_selected(selection: Any) -> None:
            if selection is None:
                app.query_one(MESSAGE_INPUT).focus()
                return

            if isinstance(selection, RewindSelection):
                selected_idx = selection.index
                restore_code = selection.restore_code
            elif isinstance(selection, int):
                selected_idx = selection
                restore_code = True
            else:
                app.query_one(MESSAGE_INPUT).focus()
                return

            if selected_idx >= 0:
                await cancel_active_workers_and_tasks(
                    app,
                    wait_workers=True,
                    timeout=1.0,
                    kill_tasks=True,
                    cancel_subagents=True,
                    session_id=curr_sid,
                )
                reset_app_state(app, is_generating=False, clear_queue=True)

                def rollback_ui(target_idx: int) -> None:
                    chat_view.rollback_to(target_idx)

                def load_text_into_input(text: str) -> None:
                    chat_input = app.query_one(MESSAGE_INPUT)
                    chat_input.load_text(text)
                    lines = chat_input.text.split("\n")
                    chat_input.move_cursor((len(lines) - 1, len(lines[-1])))

                def save_cb() -> None:
                    if hasattr(app, "save_current_session_async"):
                        asyncio.create_task(app.save_current_session_async())
                    else:
                        app.save_current_session()

                sm = getattr(app, "sm", None)
                session = sm.get(curr_sid, reload=False) if (sm and curr_sid) else None

                rewind_fn = _get_cmd_attr("rewind_session", rewind_session)
                rewind_fn(
                    app.agent,
                    curr_sid,
                    proj_path,
                    user_msgs,
                    selected_idx,
                    restore_git=restore_code,
                    session=session,
                    rollback_ui=rollback_ui,
                    load_text_into_input=load_text_into_input,
                    save_session_cb=save_cb,
                    refresh_footer_cb=lambda: app.refresh_status_footer(),
                )
            app.query_one(MESSAGE_INPUT).focus()

        result = app.push_screen(
            RewindScreen(
                msgs_with_stats,
                checkpoints_enabled=checkpoints_enabled,
                session_id=curr_sid,
                project_path=proj_path,
            ),
            callback=on_rewind_selected,
        )
        if asyncio.iscoroutine(result):
            await result


class ForkCommand(BaseCommand):
    name = "/fork"
    aliases = ["/branch"]
    description = "Fork session from a selected message"

    async def execute(self, app) -> None:
        chat_view = app.query_one(ChatView)
        if hasattr(chat_view, "load_all_older_messages") and callable(chat_view.load_all_older_messages):
            res = chat_view.load_all_older_messages()
            if asyncio.iscoroutine(res):
                await res
        user_msgs = chat_view.get_user_messages()
        if not user_msgs:
            app.notify("History is empty: no messages to fork", severity="warning")
            return

        curr_sid = getattr(app, "current_session_id", None)
        if not curr_sid or not hasattr(app, "sm"):
            app.notify("No active session to fork", severity="warning")
            return

        def on_fork_selected(selected_child_idx: int | None) -> None:
            if selected_child_idx is None:
                app.query_one(MESSAGE_INPUT).focus()
                return

            if selected_child_idx == FORK_CURRENT_STATE:
                up_to_idx = None
                msg_text = ""
                parent_sess = app.sm.get(curr_sid)
                fork_title = None
                if parent_sess:
                    base = (parent_sess.description or parent_sess.title or "Session").removesuffix(" (fork)")
                    fork_title = f"{base} (fork)"
            else:
                found = False
                msg_text = ""
                seq_idx = 0
                for i, (child_idx, text) in enumerate(user_msgs):
                    if child_idx == selected_child_idx:
                        msg_text = text
                        seq_idx = i
                        found = True
                        break

                if not found:
                    app.query_one(MESSAGE_INPUT).focus()
                    return

                up_to_idx = seq_idx
                fork_title = None
                if seq_idx > 0 and msg_text:
                    clean_msg = " ".join(msg_text.replace("\n", " ").replace("\r", " ").split())
                    if clean_msg:
                        fork_title = clean_msg
                elif seq_idx == 0:
                    parent_sess = app.sm.get(curr_sid)
                    if parent_sess:
                        base = parent_sess.title.removesuffix(" (fork)")
                        fork_title = f"{base} (fork)"

            forked = app.sm.fork_session(curr_sid, new_title=fork_title, up_to_msg_index=up_to_idx)
            if not forked:
                app.notify("Failed to fork session", severity="error")
                app.query_one(MESSAGE_INPUT).focus()
                return

            cancel_active_workers(app)
            reset_app_state(app, is_generating=False, clear_queue=True)

            app.load_session_ui(forked.id)

            chat_input = app.query_one(MESSAGE_INPUT, ChatInput)
            if msg_text:
                chat_input.load_text(msg_text)
                lines = chat_input.text.split("\n")
                chat_input.move_cursor((len(lines) - 1, len(lines[-1])))
            else:
                chat_input.load_text("")
            chat_input.focus()
            app.notify("Session forked", severity="information", timeout=1.5)

        result = app.push_screen(
            ForkScreen(user_msgs),
            callback=on_fork_selected,
        )
        if asyncio.iscoroutine(result):
            await result


class RenameCommand(BaseCommand):
    name = "/rename"
    aliases = ["/title", "/name"]
    description = "Rename the active chat session"

    async def execute(self, app) -> None:
        curr_sid = getattr(app, "current_session_id", None)
        if not curr_sid or not hasattr(app, "sm"):
            app.notify("No active session to rename", severity="warning")
            return

        sess = app.sm.get(curr_sid)
        if not sess:
            try:
                role = getattr(app, "role", "worker") or "worker"
                sess = app.sm.create_main(curr_sid, role=role)
            except Exception:
                sess = None
        if not sess:
            app.notify("Session not found", severity="error")
            return

        current_title = sess.description or sess.title
        if current_title == "Untitled":
            current_title = ""

        def on_renamed(new_title: str | None) -> None:
            if new_title is not None:
                new_title = new_title.strip()
                if new_title:
                    sess.description = new_title
                    if hasattr(app, "agent") and getattr(app.agent, "history", None):
                        sess.agent_history = list(app.agent.history)
                    app.sm.save(sess)
                    if hasattr(app, "refresh_status_footer"):
                        app.refresh_status_footer()
                    app.notify("Session renamed", severity="information", timeout=1.5)
            app.query_one(MESSAGE_INPUT).focus()

        result = app.push_screen(
            RenameSessionScreen(current_title=current_title),
            callback=on_renamed,
        )
        if asyncio.iscoroutine(result):
            await result


class DiffCommand(BaseCommand):
    name = "/diff"
    aliases = ["/changes", "/patch"]
    description = "View workspace diff since session checkpoint"

    async def execute(self, app) -> None:
        from core.application.session.actions import get_session_diff

        curr_sid = getattr(app, "current_session_id", None)
        proj_path = getattr(app.sm, "project_path", None) if hasattr(app, "sm") else None

        if not curr_sid:
            app.notify("No active session found", severity="warning")
            return

        diff_items = await get_session_diff(curr_sid, project_path=proj_path)
        if not diff_items:
            app.notify("No workspace changes found since session start", severity="information")
            return

        app.push_screen(DiffScreen(diff_items, title="Session Changes"))
