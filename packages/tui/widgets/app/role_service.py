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
    if not available_roles:
        return False
    curr = getattr(getattr(app, "agent", None), "role", getattr(app, "role", "worker")).lower()
    next_idx = (available_roles.index(curr) + 1) % len(available_roles) if curr in available_roles else 0
    new_role = available_roles[next_idx]
    project_dir = getattr(app, "project_dir", None)

    if getattr(app, "agent", None) is not None:
        from core.application.session.stream import configure_agent

        role_def = configure_agent(app.agent, new_role, app=app, project_dir=project_dir, is_subagent=False)
        new_role_name = getattr(role_def, "name", new_role.replace("_", " ").replace("-", " ").title())
    else:
        role_def = RoleRegistry.get_instance().get_role(new_role, project_dir=project_dir)
        new_role_name = role_def.name if role_def else new_role.replace("_", " ").replace("-", " ").title()

    if getattr(app, "agent", None) is not None:
        app.agent.role = new_role
        app.agent.role_name = new_role_name
    app.role = new_role
    app.role_name = new_role_name
    if hasattr(app, "sm") and hasattr(app, "current_session_id"):
        session = app.sm.get(app.current_session_id, reload=False)
        if session is not None:
            session.role = new_role
            session.role_name = new_role_name
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

    project_dir = getattr(app, "project_dir", None)
    if agent is not None:
        from core.application.session.stream import configure_agent

        role_def = configure_agent(agent, current_role, app=app, project_dir=project_dir, is_subagent=False)
        current_role_name = getattr(role_def, "name", current_role.title())
        app.agent = agent
    else:
        role_def = RoleRegistry.get_instance().get_role(current_role, project_dir=project_dir)
        current_role_name = getattr(role_def, "name", current_role.title()) if role_def else "Worker"

    app.role = current_role
    app.role_name = current_role_name
    if hasattr(app, "refresh_status_footer"):
        app.refresh_status_footer()
    return agent

