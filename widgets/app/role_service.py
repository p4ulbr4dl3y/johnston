"""Agent role switching helper for widgets.

Moves the role-registry read + role computation out of the mixin into a pure
function that takes the app. The mixin keeps only the thin guard + delegation.
"""
from __future__ import annotations

from typing import Any

from core.role_registry import RoleRegistry


def toggle_agent_role(app: Any) -> bool:
    """Toggle the agent role across all registered roles (builtin, global, project).

    Reads ``app.agent.role``, computes the next role, writes ``agent.role`` /
    ``app.role`` and refreshes the status footer. Returns True.
    """
    roles_dict = RoleRegistry.get_instance().list_roles(scope="main")
    available_roles = list(roles_dict.keys())
    curr = getattr(app.agent, "role", "worker").lower()
    next_idx = (available_roles.index(curr) + 1) % len(available_roles) if curr in available_roles else 0
    new_role = available_roles[next_idx]
    app.agent.role = new_role
    app.role = new_role
    if hasattr(app, "sm") and hasattr(app, "current_session_id"):
        session = app.sm.get(app.current_session_id, reload=False)
        if session is not None:
            session.role = new_role
            if hasattr(app, "save_current_session"):
                app.save_current_session()
    app.refresh_status_footer()
    return True
