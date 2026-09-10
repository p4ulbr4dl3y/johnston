"""Startup composition helpers for JohnstonApp (widgets/app/app.py).

Pure functions that build the app's managers, agent, resolved session id and
startup flags. Each takes the app instance explicitly as its first argument so
the composition root (``JohnstonApp.__init__``) stays a thin list of calls and
the side-effect order remains identical to the historical inline code.

All core access goes through ``tui.adapters.core_bridge`` — no direct core
imports in this module.
"""

from johnston.tui.adapters import core_bridge


def register_textual_themes(app) -> None:
    """Register all Textual themes and activate the current default theme."""
    from johnston.tui.app.theme_manager import theme_manager

    if hasattr(app, "register_theme"):
        for t in theme_manager.get_all_textual_themes():
            app.register_theme(t)
        app.theme = theme_manager.current_theme.name


def configure_global_managers(tool_name_normalizer) -> None:
    """Configure the global PermissionManager and RoleRegistry singletons."""
    core_bridge.configure_permission_manager(tool_name_normalizer)
    core_bridge.configure_role_registry(tool_name_normalizer)


def build_agent(app) -> None:
    """Create provider manager, session store, task manager, active agent and client facade."""
    core_bridge.build_core_services(app)


def resolve_session_id(app, sm, resume_session_id, continue_latest) -> None:
    """Resolve the active session id: explicit resume, continue-latest or fresh."""
    app.resume_session_id = resume_session_id
    if continue_latest and not app.resume_session_id:
        main_sessions = sm.list_main_sessions()
        if main_sessions:
            app.resume_session_id = main_sessions[0]["id"]

    if app.resume_session_id:
        sess = sm.get(app.resume_session_id)
        if sess:
            app.current_session_id = app.resume_session_id
        else:
            app.current_session_id = sm.generate_session_id()
    else:
        app.current_session_id = sm.generate_session_id()

    if hasattr(app, "client") and app.client is not None:
        app.client.session_id = app.current_session_id
        if hasattr(sm, "get"):
            app.client.session = sm.get(app.current_session_id)


def apply_startup_flags(app, theme, model, effort, sandbox, mode, role, initial_prompt) -> None:
    """Apply CLI startup flags to the app and its agent (order preserved)."""
    apply_theme(app, theme)
    apply_model(app, model)
    apply_effort(app, effort)
    apply_sandbox(app, sandbox)
    apply_mode(app, mode)
    apply_role(app, role)
    apply_initial_prompt(app, initial_prompt)


def apply_theme(app, theme) -> None:
    """Set the active theme from the ``--theme`` flag."""
    if theme:
        app.theme = theme


def apply_model(app, model) -> None:
    """Set the agent model from the ``--model`` flag."""
    if model and getattr(app, "agent", None):
        app.agent.model = model


def apply_effort(app, effort) -> None:
    """Set agent thinking/reasoning effort from the ``--effort`` flag."""
    if effort and getattr(app, "agent", None):
        app.agent.thinking_effort = effort
        app.agent.reasoning_effort = effort


def apply_sandbox(app, sandbox) -> None:
    """Override the sandbox default from the ``--sandbox``/``--no-sandbox`` flag."""
    if sandbox is not None:
        app.sandbox_enabled = sandbox
        if getattr(app, "agent", None):
            app.agent.sandbox_enabled = sandbox


def apply_mode(app, mode) -> None:
    """Set the permission execution mode from the ``--mode`` flag."""
    if mode:
        core_bridge.apply_execution_mode(app, mode)


def apply_role(app, role) -> None:
    """Apply the role to the agent and track it on the app from the ``--role`` flag."""
    if role and getattr(app, "agent", None):
        core_bridge.apply_role_to_agent(app, role)


def apply_initial_prompt(app, initial_prompt) -> None:
    """Store the ``--prompt`` value (also when no agent was created)."""
    app.initial_prompt = initial_prompt
