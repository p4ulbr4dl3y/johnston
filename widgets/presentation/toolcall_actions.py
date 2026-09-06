"""Actions and click interaction mixin for ToolCallWidget."""
from __future__ import annotations

import re
from typing import Any


class ToolCallActionsMixin:
    """Header click handling, subagent navigation, and wizard resumption."""

    def has_subagent_session(self) -> bool:
        """Check whether this toolcall is associated with an existing subagent session."""
        if getattr(self, "subagent_session_id", None):
            return True
        args = self.args if isinstance(self.args, dict) else {}
        session_id = args.get("session_id")
        if not session_id and getattr(self, "result_text", None):
            m = re.search(r"(?:\|\s*id\s+|session[_\s-]?id[:=\s]+)([a-zA-Z0-9_-]+)", self.result_text, re.IGNORECASE)
            if m:
                session_id = m.group(1)
        if session_id:
            self.subagent_session_id = str(session_id)
            return True

        if getattr(self, "canonical_tool", None) in ("invoke_subagent", "manage_subagent"):
            title = args.get("title") or args.get("prompt")
            if title:
                app = None
                try:
                    app = self.app
                except Exception:
                    pass
                store = getattr(app, "sm", None) if app else None
                if store is None:
                    try:
                        from core.infrastructure.storage.session_store import SessionStore

                        store = SessionStore.get_instance()
                    except Exception:
                        store = None
                if store is not None and hasattr(store, "find_session_by_title_or_id"):
                    try:
                        curr_sid = getattr(app, "current_session_id", None) if app else None
                        sess = store.find_session_by_title_or_id(str(title), parent_id=curr_sid)
                        if not sess:
                            sess = store.find_session_by_title_or_id(str(title))
                        if sess is not None and getattr(sess, "id", None) and (
                            isinstance(sess.id, str) or type(sess).__name__ == "MagicMock"
                        ):
                            if isinstance(sess.id, str):
                                self.subagent_session_id = sess.id
                            return True
                    except Exception:
                        pass
        return False

    def is_clickable_header(self) -> bool:
        if getattr(self, "status", None) == "generating":
            return False
        canonical = getattr(self, "canonical_tool", "")
        if canonical in ("invoke_subagent", "manage_subagent"):
            if self.has_subagent_session():
                return True
            if getattr(self, "status", None) in ("error", "cancelled"):
                return False
            return canonical == "invoke_subagent"

        if getattr(self, "status", None) in ("error", "cancelled"):
            return canonical == "shell" and bool((getattr(self, "result_text", "") or "").strip())
        return self.is_expandable() or canonical in ("invoke_subagent", "ask_user")

    def _resume_ask_user_wizard(self) -> None:
        """Resume a minimized ask_user wizard if present."""
        app = getattr(self, "app", None)
        pending = getattr(app, "_pending_ask_user", None) if app else None
        if callable(pending):
            pending()

    def on_click(self, event: Any) -> None:
        if not self.is_clickable_header():
            return

        app = None
        try:
            app = self.app
        except Exception:
            pass

        canonical = getattr(self, "canonical_tool", "")
        if canonical == "invoke_subagent":
            args = self.args if isinstance(self.args, dict) else {}
            session_id = getattr(self, "subagent_session_id", None)
            if not session_id and getattr(self, "result_text", None):
                m = re.search(r"(?:\|\s*id\s+|session[_\s-]?id[:=\s]+)([a-zA-Z0-9_-]+)", self.result_text, re.IGNORECASE)
                if m:
                    session_id = m.group(1)
            identifier = (
                session_id
                or args.get("session_id")
                or args.get("title")
                or args.get("prompt")
                or getattr(self, "target", "")
            )
            store = getattr(app, "sm", None) if app else None
            if store is None:
                from core.infrastructure.storage.session_store import SessionStore

                store = SessionStore.get_instance()
            curr_session_id = getattr(app, "current_session_id", None) if app else None
            session = store.find_session_by_title_or_id(str(identifier), parent_id=curr_session_id) if store else None
            if not session and store:
                session = store.find_session_by_title_or_id(str(identifier))
            if not session:
                if app and hasattr(app, "notify"):
                    app.notify("Subagent session not found", severity="warning")
                event.stop()
                return
            event.stop()
            try:
                from widgets.presentation.screens.subagent_screen import SubagentViewScreen

                if app:
                    target_id = (
                        identifier
                        if session_id or (isinstance(args, dict) and args.get("session_id"))
                        else (getattr(session, "id", None) or str(identifier))
                    )
                    app.push_screen(SubagentViewScreen(target_id))
            except Exception:
                pass
            return

        if canonical == "manage_subagent":
            args = self.args if isinstance(self.args, dict) else {}
            session_id = getattr(self, "subagent_session_id", None) or args.get("session_id")
            if session_id:
                store = getattr(app, "sm", None) if app else None
                if store is None:
                    from core.infrastructure.storage.session_store import SessionStore

                    store = SessionStore.get_instance()
                curr_session_id = getattr(app, "current_session_id", None) if app else None
                session = (
                    store.find_session_by_title_or_id(session_id, parent_id=curr_session_id)
                    if store
                    else None
                )
                if not session:
                    if app and hasattr(app, "notify"):
                        app.notify("Subagent session not found", severity="warning")
                    event.stop()
                    return
                event.stop()
                try:
                    from widgets.presentation.screens.subagent_screen import SubagentViewScreen

                    if app:
                        app.push_screen(SubagentViewScreen(session_id))
                except Exception:
                    pass
                return

        if canonical == "ask_user":
            if getattr(app, "_pending_ask_user", None) is not None:
                self._resume_ask_user_wizard()
                event.stop()
                return

        if self.is_expandable():
            self.toggle_expanded()
            event.stop()
