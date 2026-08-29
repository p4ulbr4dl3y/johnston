"""State-building helpers for the status footer.

Pure aggregators: they read application/session/provider state (via ``app``
and optionally the widget, used only as a cache holder) and return ready
rendering data. Widgets keep rendering, timers, and spinner logic here by
delegating collection.

``format_display_path`` intentionally stays in ``widgets/status_footer.py``
(it is a pure path helper also used by the render grid and imported directly
by tests).
"""
from __future__ import annotations

import asyncio
import os
import time

from core.infrastructure.runtime.thinking_effort import display_thinking_effort
from core.models_catalog import catalog


def get_mcp_manager():
    """Resolve MCP manager dynamically from core infrastructure."""
    import core.infrastructure.mcp as mcp_mod

    return mcp_mod.get_mcp_manager()


def _collect_cache(app):
    """(sync, thread-safe) Read provider/skills/mcp state off the event loop."""
    pm = getattr(app, "pm", None)
    try:
        providers = pm.load_providers() if pm else {}
    except Exception:
        providers = {}
    try:
        from core.application.skills.manager import get_skill_manager

        all_skills = get_skill_manager().list_skills(include_hidden=True)
        skills_total = len(all_skills)
        skills_visible = sum(1 for s in all_skills if not s.hidden)
    except Exception:
        skills_total, skills_visible = 0, 0
    try:
        mcp_servers = get_mcp_manager().load_servers()
    except Exception:
        mcp_servers = []
    return providers, skills_visible, skills_total, mcp_servers


async def refresh_footer_cache(app, widget) -> None:
    """Async background loader for footer caches (providers/skills/mcp)."""
    try:
        providers, skills_visible, skills_total, mcp_servers = await asyncio.to_thread(_collect_cache, app)
    except Exception:
        return
    widget._st_cached_providers = providers
    widget._st_cached_skills = (skills_visible, skills_total)
    widget._st_cached_mcp_servers = mcp_servers
    widget._st_cache_time = time.time()
    try:
        if getattr(widget, "is_mounted", True):
            widget.refresh_footer()
    except Exception:
        pass


def _ensure_cache(app, widget) -> None:
    """Kick off a background cache load when the widget has no fresh values yet."""
    if not widget:
        return
    now = time.time()
    if getattr(widget, "_st_cache_time", 0) and (now - getattr(widget, "_st_cache_time", 0) < 5.0):
        return
    if getattr(widget, "_st_cache_loading", False):
        return
    widget._st_cache_loading = True

    async def _bg() -> None:
        try:
            await refresh_footer_cache(app, widget)
        finally:
            widget._st_cache_loading = False

    try:
        import asyncio as _async

        _async.get_running_loop().create_task(_bg())
    except RuntimeError:
        # No running loop (e.g. tests): run synchronously, mirror the old behavior.
        try:
            providers, skills_visible, skills_total, mcp_servers = _collect_cache(app)
            widget._st_cached_providers = providers
            widget._st_cached_skills = (skills_visible, skills_total)
            widget._st_cached_mcp_servers = mcp_servers
            widget._st_cache_time = time.time()
        except Exception:
            pass
        widget._st_cache_loading = False


def build_status_kwargs(app, widget=None) -> dict:
    """Collect all footer status values from the app into a render kwargs dict.

    ``widget`` is optional and used only as a small TTL-cache holder for the
    provider/skills/mcp-server enumerations (5s) plus the ``_active_mcp_count``
    hook. Heavy reads (``pm.load_providers()``, skills listing, MCP server file
    load) run off the event loop via ``refresh_footer_cache``; this function
    only reads the cached values so the footer timer never blocks.
    """
    if widget is not None:
        _ensure_cache(app, widget)
        providers = getattr(widget, "_st_cached_providers", None)
        if providers is None:
            providers = {}
        cached_skills = getattr(widget, "_st_cached_skills", (0, 0))
        skills_visible, skills_total = cached_skills
        cached_mcp = getattr(widget, "_st_cached_mcp_servers", None)
        mcp_servers = cached_mcp if cached_mcp is not None else []
    else:
        # No cache holder: fall back to a lightweight synchronous read subset.
        try:
            providers, skills_visible, skills_total, mcp_servers = _collect_cache(app)
        except Exception:
            providers, skills_visible, skills_total, mcp_servers = {}, 0, 0, []

    from core.infrastructure.runtime.task_collection import collect_current_tasks

    pm = getattr(app, "pm", None)
    pkey = pm.get_active_provider_key() if pm else "default"
    agent = getattr(app, "agent", None)
    model_name = getattr(agent, "model", "")
    provider_info = providers.get(pkey, {}) if isinstance(providers, dict) else {}
    provider_display = provider_info.get("name", pkey) if provider_info else pkey
    is_connected = pm.is_provider_connected(pkey, provider_info) if (pm and pkey) else False
    clean_model = catalog.get_model_display_name(pkey, model_name)
    if not clean_model:
        clean_model = "[Select model: /models]"
    if pm and hasattr(pm, "get_provider_thinking_effort"):
        effort_val = pm.get_provider_thinking_effort(pkey, model_name)
    else:
        effort_val = getattr(agent, "thinking_effort", None)
    thinking_effort = display_thinking_effort(effort_val)
    metrics = agent.get_metrics() if (agent and hasattr(agent, "get_metrics")) else {}

    # Count only servers that are actually loading (enabled, stdio
    # command) and of those, only the ones that finished loading: a
    # running client that discovered tools and has no error. Pending or
    # errored servers don't count, so while loading the footer flips to
    # the spinner.
    mcp_total = len(mcp_servers)
    try:
        count_fn = getattr(get_mcp_manager(), "active_server_count", None)
        mcp_active = 0
        if callable(count_fn):
            mcp_active = count_fn(mcp_servers) or 0
    except Exception:
        mcp_active = 0

    tasks = collect_current_tasks(app, getattr(app, "current_session_id", None))
    bg_tasks = tasks.shell_tasks
    sessions = tasks.subagent_tasks

    active_bg_tasks = len(
        [t for t in bg_tasks if getattr(t, "is_running", False) and getattr(t, "is_background", True)]
    )

    subagents_active = len([s for s in sessions if getattr(s, "status", "") == "running"])
    subagents_total = len(sessions)

    agent_role = getattr(agent, "role", "worker")

    attachments_count = 0
    try:
        if app:
            from widgets.presentation.screens.constants import MESSAGE_INPUT

            chat_input = app.query_one(MESSAGE_INPUT)
            attachments_count = len(getattr(chat_input, "clipboard_attachments", []))
    except Exception:
        attachments_count = 0

    from core.permission_manager import PermissionManager

    execution_mode = PermissionManager.get_instance().execution_mode.value

    return {
        "provider_key": pkey,
        "provider_display": provider_display,
        "is_connected": is_connected,
        "model_name": model_name,
        "clean_model": clean_model,
        "agent_role": agent_role,
        "directory": os.getcwd(),
        "active_bg_tasks": active_bg_tasks,
        "subagents_active": subagents_active,
        "subagents_total": subagents_total,
        "context_used": metrics.get("context_used", 0),
        "total_tokens": metrics.get("total_tokens", 0),
        "context_window": metrics.get("context", "128k"),
        "context_limit": metrics.get("context_limit", 128000),
        "cost_usd": metrics.get("cost_usd", 0.0),
        "thinking_effort": thinking_effort,
        "skills_visible": skills_visible,
        "skills_total": skills_total,
        "mcp_active": mcp_active,
        "mcp_total": mcp_total,
        "attachments_count": attachments_count,
        "sandbox_enabled": getattr(app, "sandbox_enabled", False) if app else False,
        "execution_mode": execution_mode,
    }

