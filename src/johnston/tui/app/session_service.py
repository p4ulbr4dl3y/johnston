"""Session persistence service for Johnston TUI.

Encapsulates session UI loading, session state writing, saving (sync/async),
and resume hints.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

from johnston.core.dto import AgentMode
from johnston.tui.presentation.widgets.chat_container import ChatView

logger = logging.getLogger(__name__)

_global_session_write_lock = threading.Lock()


class SessionPersistenceService:
    """Session UI loading, state writing, saving, and resume hints."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._last_save_time: float = 0.0

    def load_session_ui(self, session_id: str, read_only: bool = False) -> None:
        """Load session state into UI and agent history."""
        app = self.app
        session = app.sm.get(session_id)
        if not session:
            return

        old_sid = getattr(app, "current_session_id", None)
        if old_sid and old_sid != session_id and hasattr(app.sm, "release_session_lock"):
            app.sm.release_session_lock(old_sid)

        app.current_session_id = session_id
        app.is_read_only = read_only
        app.pending_fork = None

        try:
            from johnston.tui.presentation.widgets.chat_input import DEFAULT_PLACEHOLDER, FORK_PLACEHOLDER, ChatInput

            chat_input = app.query_one("#message-input", ChatInput)
            if read_only:
                chat_input.placeholder = FORK_PLACEHOLDER
            else:
                chat_input.placeholder = DEFAULT_PLACEHOLDER
                if hasattr(chat_input, "update_placeholder"):
                    chat_input.update_placeholder()
        except Exception:
            pass

        if not read_only:
            if hasattr(app.sm, "acquire_session_lock"):
                app.sm.acquire_session_lock(session_id)
            app.sm.set_active_session_id(session_id)

        chat_view = app.query_one(ChatView)
        try:
            from johnston.tui.presentation.widgets.plan_notch import PlanNotch

            notches = list(app.query(PlanNotch)) if hasattr(app, "query") else []
            for n in notches:
                if hasattr(n, "clear_plan"):
                    n.clear_plan()
        except Exception:
            pass

        async def _restore_messages(sess: Any) -> None:
            task_mgr = getattr(app, "task_manager", None)
            try:
                await ChatView.load_session(chat_view, sess, task_manager=task_mgr)
            except Exception as err:
                try:
                    if hasattr(app, "notify"):
                        app.notify(f"UI restoration failed: {err}", severity="warning")
                except Exception:
                    pass

            # Delay plan notch appearance so dialogue renders first
            await asyncio.sleep(0.15)
            try:
                from johnston.tui.presentation.widgets.plan_notch import PlanNotch

                notches = list(app.query(PlanNotch)) if hasattr(app, "query") else []
                if not notches and hasattr(app, "screen") and app.screen:
                    notches = list(app.screen.query(PlanNotch))
                cur_plan = getattr(app, "current_plan", None)
                for notch in notches:
                    if cur_plan:
                        notch.set_plan(cur_plan, getattr(app, "current_plan_explanation", ""))
                    else:
                        notch.clear_plan()
            except Exception:
                pass

        if hasattr(app, "run_worker"):
            app.run_worker(_restore_messages(session))

        # Restore agent context
        if app.agent is None and hasattr(app, "pm") and app.pm:
            try:
                app.agent = app.pm.create_active_agent(
                    role=session.role if hasattr(session, "role") and session.role else "worker"
                )
            except Exception:
                app.agent = None

        if app.agent is not None:
            app.agent.app = app
            # Resumed TUI agents are interactive (client default is HEADLESS).
            agent_is_subagent = getattr(app.agent, "is_subagent", False) is True
            app.agent.mode = (
                AgentMode.SUBAGENT if agent_is_subagent else AgentMode.INTERACTIVE
            )
            app.agent.is_headless = False
        if app.agent is not None and hasattr(app.agent, "history"):
            app.agent.history = session.agent_history
            app.agent.tokens_input = session.tokens_input
            app.agent.tokens_output = session.tokens_output
            app.agent.total_tokens = session.total_tokens
            app.agent.cost_usd = session.cost_usd
            app.agent.tokens_cache_read = session.tokens_cache_read

            if hasattr(session, "role") and session.role:
                app.agent.role = session.role
                app.role = session.role
            else:
                app.agent.role = "worker"
                app.role = "worker"

            ctx = session.last_context_tokens
            if not ctx and app.agent.history:
                from johnston.tui.app.session_state import recompute_context_tokens

                ctx = recompute_context_tokens(app.agent, session.last_context_tokens)
            app.agent.last_context_tokens = ctx
            if hasattr(app.agent, "_ctx_api_tokens"):
                # Resumed sessions use the stored ctx as baseline: drop the
                # API anchor so current_context_tokens() falls back to the
                # heuristic until the next API report.
                app.agent._ctx_api_tokens = 0
                app.agent._ctx_api_hist_tokens = 0
        elif hasattr(session, "role") and session.role:
            app.role = session.role

        # Restore active plan state from session messages
        from johnston.tui.adapters import core_bridge

        restore_plan_from_messages = core_bridge.get_session_actions()["restore_plan_from_messages"]

        restored_plan = None
        restored_explanation = ""
        try:
            saved_msgs = getattr(session, "messages", [])
            msg_seq = list(saved_msgs) if saved_msgs is not None else []
            restored_plan, restored_explanation = restore_plan_from_messages(msg_seq)
        except Exception:
            pass

        app.current_plan = restored_plan
        app.current_plan_explanation = restored_explanation

        # Restore project dir / branch state if recorded and path exists
        sess_dir = getattr(session, "project_dir", None)
        sess_branch = getattr(session, "branch_name", "") or ""
        if isinstance(sess_dir, str) and sess_dir:
            if os.path.isdir(sess_dir) and hasattr(app, "switch_project_dir"):
                if sess_dir != getattr(app, "project_dir", None) or sess_branch != getattr(
                    getattr(app, "agent", None), "worktree_branch", ""
                ):
                    app.switch_project_dir(sess_dir, sess_branch)
            elif not os.path.isdir(sess_dir):
                root_dir = getattr(app, "project_dir", "") or os.getcwd()
                session.project_dir = root_dir
                session.branch_name = ""
                if getattr(app, "agent", None):
                    app.agent.worktree_branch = ""
                if hasattr(app, "notify"):
                    try:
                        app.notify(
                            "Worktree directory no longer exists. Resumed in project root.",
                            severity="warning",
                        )
                    except Exception:
                        pass
        elif isinstance(sess_branch, str) and sess_branch and getattr(app, "agent", None):
            app.agent.worktree_branch = sess_branch

        if hasattr(app, "refresh_status_footer"):
            app.refresh_status_footer()

    def get_current_session_data(self) -> dict[str, Any] | None:
        """Collect session data from the transcript session store (source of truth).

        Delegates collection to the pure aggregator in widgets/app/session_state.
        """
        from johnston.tui.app.session_state import collect_session_data

        return collect_session_data(self.app)

    _get_current_session_data = get_current_session_data

    def write_session_data(self, session_data: dict[str, Any]) -> bool:
        """Write collected session data into the store (no UI access — safe for threads)."""
        app = self.app
        if getattr(app, "is_read_only", False):
            return True
        with _global_session_write_lock:
            existing = app.sm.get(app.current_session_id, reload=False)
            is_new = existing is None
            session = existing or app.sm.create_main(app.current_session_id)
            changed = is_new

            new_title = session_data.get("title")
            if new_title and session.title != new_title:
                session.title = new_title
                changed = True

            new_role = session_data.get("role")
            if new_role and session.role != new_role:
                session.role = new_role
                changed = True

            for attr, default in (
                ("messages", []),
                ("agent_history", []),
                ("tokens_input", 0),
                ("tokens_output", 0),
                ("total_tokens", 0),
                ("cost_usd", 0.0),
                ("last_context_tokens", 0),
                ("tokens_cache_read", 0),
                ("project_dir", ""),
                ("branch_name", ""),
            ):
                new_value = session_data.get(attr, default)
                if getattr(session, attr) != new_value:
                    setattr(session, attr, new_value)
                    changed = True

            saved = True
            if changed:
                session.touch()
                saved = app.sm.save(session)
            if hasattr(app.sm, "set_active_session_id"):
                app.sm.set_active_session_id(app.current_session_id)
            return bool(saved)

    _write_session_data = write_session_data

    def _collect_session_data(self) -> dict[str, Any] | None:
        getter = getattr(self.app, "_get_current_session_data", None)
        if getter is not None:
            from unittest.mock import Mock

            from johnston.tui.mixins.session_persistence import SessionPersistenceMixin

            is_instance_mock = "_get_current_session_data" in getattr(self.app, "__dict__", {}) or isinstance(
                getter, Mock
            )
            is_override = getattr(getter, "__func__", None) not in (
                None,
                SessionPersistenceMixin._get_current_session_data,
            )
            if is_instance_mock or is_override:
                return getter()
        return self.get_current_session_data()

    def _persist_session_data(self, session_data: dict[str, Any]) -> bool:
        writer = getattr(self.app, "_write_session_data", None)
        if writer is not None:
            from unittest.mock import Mock

            from johnston.tui.mixins.session_persistence import SessionPersistenceMixin

            is_instance_mock = "_write_session_data" in getattr(self.app, "__dict__", {}) or isinstance(
                writer, Mock
            )
            is_override = getattr(writer, "__func__", None) not in (
                None,
                SessionPersistenceMixin._write_session_data,
            )
            if is_instance_mock or is_override:
                return writer(session_data)
        return self.write_session_data(session_data)

    def save_current_session(self) -> None:
        """Save complete UI element state to ~/.johnston/workspaces/<project>/sessions."""
        session_data = self._collect_session_data()
        if session_data is not None:
            ok = self._persist_session_data(session_data)
            if ok is False and hasattr(self.app, "notify"):
                self.app.notify("Failed to save session to disk", severity="error", timeout=4.0)
            if hasattr(self.app, "refresh_status_footer"):
                self.app.refresh_status_footer()

    async def save_current_session_async(self, force: bool = False) -> None:
        """Collect session data on main UI thread, then save to disk in background thread."""
        now = time.time()
        last_save = getattr(self.app, "_last_session_save_time", getattr(self, "_last_save_time", 0.0))
        if not force and (now - last_save < 1.5):
            return
        setattr(self.app, "_last_session_save_time", now)
        self._last_save_time = now
        session_data = self._collect_session_data()
        if session_data is not None:
            ok = await asyncio.to_thread(self._persist_session_data, session_data)
            if ok is False and hasattr(self.app, "notify"):
                self.app.notify("Failed to save session to disk", severity="error", timeout=4.0)
            if hasattr(self.app, "refresh_status_footer"):
                self.app.refresh_status_footer()

    def get_resume_hint(self) -> str | None:
        """Return CLI command string to resume active session if it contains messages."""
        app = self.app
        sid = getattr(app, "current_session_id", None)
        sm = getattr(app, "sm", None)
        if not sid or sm is None:
            return None
        try:
            sess = sm.get(sid)
            if sess and (getattr(sess, "messages", None) or getattr(sess, "agent_history", None)):
                return f"johnston --resume {sid}"
        except Exception:
            pass
        return None
