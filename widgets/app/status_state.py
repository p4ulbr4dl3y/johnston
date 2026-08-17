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

from core.infrastructure.mcp import get_mcp_manager
from core.infrastructure.runtime.thinking_effort import display_thinking_effort
from core.models_catalog import catalog, format_context_tokens


def _collect_cache(app):
    """(sync, thread-safe) Read provider/skills/mcp state off the event loop."""
    pm = getattr(app, "pm", None)
    try:
        providers = pm.load_providers() if pm else {}
    except Exception:
        providers = {}
    try:
        from core.application.skills.manager import SkillManager

        all_skills = SkillManager().list_skills(include_hidden=True)
        skills_total = len(all_skills)
        skills_visible = sum(1 for s in all_skills if not s.hidden)
    except Exception:
        skills_total, skills_visible = 0, 0
    try:
        from core.infrastructure.mcp import get_mcp_manager

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
    else:
        # No cache holder: fall back to a lightweight synchronous read subset.
        try:
            _collect_cache(app)
        except Exception:
            pass
    from core.infrastructure.runtime.task_collection import collect_current_tasks

    pm = getattr(app, "pm", None)
    pkey = pm.get_active_provider_key() if pm else "default"
    agent = getattr(app, "agent", None)
    model_name = getattr(agent, "model", "")
    providers = getattr(widget, "_st_cached_providers", None)
    if providers is None:
        if widget is not None:
            # Cache not ready yet (background load in flight): avoid blocking the
            # footer timer on disk; the background loader will re-render shortly.
            providers = {}
        else:
            providers = pm.load_providers() if pm else {}
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

    cached_skills = getattr(widget, "_st_cached_skills", None)
    if cached_skills is None:
        _ensure_cache(app, widget)
        cached_skills = getattr(widget, "_st_cached_skills", (0, 0))
    skills_visible, skills_total = cached_skills

    cached_mcp = getattr(widget, "_st_cached_mcp_servers", None)
    if cached_mcp is None:
        cached_mcp = get_mcp_manager().load_servers()
        widget._st_cached_mcp_servers = cached_mcp
    mcp_servers = cached_mcp

    # Count only servers that are actually loading (enabled, stdio
    # command) and of those, only the ones that finished loading: a
    # running client that discovered tools and has no error. Pending or
    # errored servers don't count, so while loading the footer flips to
    # the spinner.
    mcp_total = 0
    for s in mcp_servers:
        if s.get("url") and not s.get("command"):
            continue
        mcp_total += 1
    mcp_active = widget._active_mcp_count(mcp_servers) if widget is not None else 0

    tasks = collect_current_tasks(app, getattr(app, "current_session_id", None))
    bg_tasks = tasks.shell_tasks
    sessions = tasks.subagent_tasks

    active_bg_tasks = len(
        [t for t in bg_tasks if getattr(t, "is_running", False) and getattr(t, "is_background", True)]
    )

    subagents_active = len([s for s in sessions if getattr(s, "status", "") == "running"])
    subagents_total = len(sessions)

    agent_role = getattr(agent, "role", "worker")

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
    }


def build_subagent_status_kwargs(
    app,
    session,
    *,
    spinner_running: bool,
    spinner_idx: int,
) -> tuple:
    """Collect subagent footer values and return them as a ``_render_subagent`` arg tuple.

    The tuple order matches ``StatusFooter._render_subagent`` signature:
    ``(role_formatted, provider_display, clean_model, is_connected, model_name,
    context_used, total_tokens, context_limit, context_window, cost_usd,
    thinking_effort, directory)``.

    ``spinner_running`` / ``spinner_idx`` are passed in; the widget decides
    whether the spinner is shown and manages its timer — this function only
    renders the spinner frame into ``role_formatted`` when told to.
    """
    from widgets.status_footer import SPINNER_FRAMES

    agent = getattr(session, "agent", None)
    app_agent = getattr(app, "agent", None) if app else None
    role = getattr(agent, "role", "worker") if agent else getattr(session, "role", "worker")
    effort_val = getattr(agent, "thinking_effort", None) if agent else getattr(app_agent, "thinking_effort", None)
    thinking_effort = display_thinking_effort(effort_val) if effort_val else "auto"
    metrics = agent.get_metrics() if (agent and hasattr(agent, "get_metrics")) else {}
    provider_key = (
        getattr(agent, "provider_key", "")
        if agent
        else (getattr(app_agent, "provider_key", "") if app_agent else "")
    )

    pm = getattr(app, "pm", None)
    if not provider_key and pm:
        provider_key = pm.get_active_provider_key()
    providers = pm.load_providers() if pm else {}
    provider_info = providers.get(provider_key, {}) if isinstance(providers, dict) else {}
    provider_display = provider_info.get("name", provider_key) if provider_info else provider_key
    is_connected = pm.is_provider_connected(provider_key, provider_info) if (pm and provider_key) else False

    model_name = (
        getattr(agent, "model", "")
        if agent
        else (getattr(app_agent, "model", "") if app_agent else provider_info.get("model", ""))
    )
    clean_model = catalog.get_model_display_name(provider_key, model_name) if model_name else ""
    if not clean_model:
        clean_model = "[Select model: /models]"

    directory = getattr(session, "project_dir", "") or os.path.basename(os.path.realpath(os.getcwd()))
    if os.path.basename(directory) != directory:
        directory = os.path.basename(os.path.normpath(directory)) or directory

    context_used = metrics.get("context_used") or getattr(session, "last_context_tokens", 0)
    total_tokens = metrics.get("total_tokens") or getattr(session, "total_tokens", 0)
    cost_usd = metrics.get("cost_usd") or getattr(session, "cost_usd", 0.0)
    context_limit = (
        metrics.get("context_limit")
        or getattr(agent, "context_limit", None)
        or getattr(app_agent, "context_limit", 128000)
        or 128000
    )
    context_window = metrics.get("context") or format_context_tokens(context_limit)

    role_formatted = (
        f"{SPINNER_FRAMES[spinner_idx % len(SPINNER_FRAMES)]} " if spinner_running else ""
    )
    role_formatted += role.capitalize()

    return (
        role_formatted,
        provider_display or provider_key.capitalize(),
        clean_model or "[Select model: /models]",
        is_connected,
        model_name,
        context_used,
        total_tokens,
        context_limit,
        context_window,
        cost_usd,
        thinking_effort,
        directory,
    )
