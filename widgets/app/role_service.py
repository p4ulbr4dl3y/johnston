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


def reconcile_active_agent(
    app: Any,
    provider_key: str | None = None,
    history: list[Any] | None = None,
) -> Any:
    """Reconcile active agent with UI state, preserving history, role, and status footer."""
    old_history = history if history is not None else list(getattr(getattr(app, "agent", None), "history", []))
    current_role = getattr(app, "role", getattr(getattr(app, "agent", None), "role", "worker"))
    pm = getattr(app, "pm", None)
    if pm is not None and hasattr(pm, "recreate_active_agent"):
        try:
            agent = pm.recreate_active_agent(provider_key=provider_key, history=old_history, role=current_role)
        except TypeError:
            agent = pm.recreate_active_agent(app, provider_key=provider_key)
    elif pm is not None and hasattr(pm, "create_active_agent"):
        if provider_key and hasattr(pm, "set_active_provider_key"):
            pm.set_active_provider_key(provider_key)
        agent = pm.create_active_agent()
        if agent is not None:
            if old_history:
                agent.history = list(old_history)
            agent.role = current_role
    else:
        agent = None

    if agent is not None:
        agent.app = app
        app.agent = agent
    app.role = current_role
    if hasattr(app, "refresh_status_footer"):
        app.refresh_status_footer()
    return agent
