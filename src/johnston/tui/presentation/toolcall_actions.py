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
        from johnston.core.application.session.facade import resolve_subagent_from_toolcall

        args = self.args if isinstance(self.args, dict) else {}
        call_args = dict(args)
        if getattr(self, "result_text", None):
            call_args.setdefault("result_text", self.result_text)
        app = None
        try:
            app = self.app
        except Exception:
            pass
        session_id = resolve_subagent_from_toolcall(getattr(self, "canonical_tool", None) or "", call_args, app)
        return bool(session_id)

    def bind_subagent_session(self, session_id: str | None = None) -> str | None:
        """Explicitly bind subagent_session_id once during initialization or on explicit event."""
        if session_id:
            self.subagent_session_id = str(session_id)
            return self.subagent_session_id
        if getattr(self, "subagent_session_id", None):
            return self.subagent_session_id

        from johnston.core.application.session.facade import resolve_subagent_from_toolcall

        args = self.args if isinstance(self.args, dict) else {}
        call_args = dict(args)
        if getattr(self, "result_text", None):
            call_args.setdefault("result_text", self.result_text)
        app = None
        try:
            app = self.app
        except Exception:
            pass
        sid = resolve_subagent_from_toolcall(getattr(self, "canonical_tool", None) or "", call_args, app)
        if sid:
            self.subagent_session_id = str(sid)
            return self.subagent_session_id
        return getattr(self, "subagent_session_id", None)

    def is_clickable_header(self) -> bool:
        if getattr(self, "status", None) == "generating":
            return False
        canonical = getattr(self, "canonical_tool", "")
        if canonical in ("invoke_subagent", "message_subagent"):
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
            from johnston.core.application.session.facade import resolve_session_by_title

            curr_session_id = getattr(app, "current_session_id", None) if app else None
            session = resolve_session_by_title(str(identifier), parent_id=curr_session_id, app=app) if identifier else None
            if not session:
                if app and hasattr(app, "notify"):
                    app.notify("Subagent session not found", severity="warning")
                event.stop()
                return
            event.stop()
            try:
                from johnston.tui.presentation.screens.subagent_screen import SubagentViewScreen

                if app:
                    target_id = (
                        identifier
                        if session_id or (isinstance(args, dict) and args.get("session_id"))
                        else (getattr(session, "id", None) or str(identifier))
                    )
                    self.bind_subagent_session(target_id)
                    app.push_screen(SubagentViewScreen(target_id))
            except Exception:
                pass
            return

        if canonical == "message_subagent":
            args = self.args if isinstance(self.args, dict) else {}
            session_id = getattr(self, "subagent_session_id", None) or args.get("id") or args.get("session_id")
            if session_id:
                from johnston.core.application.session.facade import resolve_session_by_title

                curr_session_id = getattr(app, "current_session_id", None) if app else None
                session = resolve_session_by_title(str(session_id), parent_id=curr_session_id, app=app)
                if not session:
                    if app and hasattr(app, "notify"):
                        app.notify("Subagent session not found", severity="warning")
                    event.stop()
                    return
                event.stop()
                try:
                    from johnston.tui.presentation.screens.subagent_screen import SubagentViewScreen

                    if app:
                        self.bind_subagent_session(session_id)
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
