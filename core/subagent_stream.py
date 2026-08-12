"""Subagent streaming helpers operating on the unified AgentSession model.

Subagent sessions are AgentSession records (kind="subagent") stored per-project
under sessions/<parent_id>.subagents/ via SessionStore.
"""

import asyncio
from typing import Any, Callable, Optional

from core.defaults.tools import SUBAGENT_EXCLUDED_TOOLS
from core.session_manager import STATUS_CANCELLED, STATUS_COMPLETED, STATUS_ERROR, AgentSession


def record_subagent_step(step: tuple, session: AgentSession, text_accumulator: list) -> None:
    """Records a subagent execution step into the session in canonical message format.

    Raw stream events (thinking_start/delta/end, bot_delta/text,
    tool_result) are canonicalized here into shared types (thinking/bot/tool)
    before being appended via AgentSession.add_event.
    """
    import math

    if not step:
        return
    etype = step[0]
    val1 = step[1] if len(step) > 1 else ""
    val2 = step[2] if len(step) > 2 else ""
    val3 = step[3] if len(step) > 3 else None

    if etype == "thinking_start":
        session.add_event({"type": "thinking", "text": val1})
    elif etype == "thinking_delta":
        session.add_event({"type": "thinking", "text": val1})
    elif etype == "thinking_end":
        try:
            dur = float(val1)
            if not math.isfinite(dur):
                dur = 0.0
        except (ValueError, TypeError):
            dur = 0.0
        session.add_event({"type": "thinking", "text": val2, "duration": dur})
    elif etype == "thinking":
        # Informational thinking (auto-compaction/retry notices): always final.
        session.add_event({"type": "thinking", "text": val1, "duration": 0.0})
    elif etype == "tool":
        targs = val3 if isinstance(val3, dict) else {}
        session.add_event({"type": "tool", "tool_type": val1, "target": val2, "args": targs})
    elif etype == "tool_result":
        session.add_event({"type": "tool", "result_text": val1})
    elif etype == "bot_delta":
        text_accumulator[0] = text_accumulator[0] + val1
        session.add_event({"type": "bot", "text": text_accumulator[0]})
    elif etype in ("bot_text", "outro"):
        text_accumulator[0] = val1
        session.add_event({"type": "bot", "text": text_accumulator[0], "final": True})
    elif etype == "event_divider":
        session.add_event({"type": "event_divider", "text": val1 or "Session Compacted"})


def _apply_provider_config(subagent: Any, provider_key: str) -> None:
    """Rebind an existing subagent agent to a different provider in place.

    Builds a fresh agent for the target provider and copies its configuration
    (including the HTTP client bound to that provider's base_url/api_key) onto
    the existing subagent object, preserving caller-attached identity fields.
    Keeps the same object so session.agent and surrounding code stay valid.
    """
    from core.provider_manager import ProviderManager

    pm = ProviderManager()
    rebuilt = pm.create_agent_for_provider(provider_key)
    if rebuilt is None:
        return

    # Preserve identity plumbing attached by the caller.
    preserved = {
        name: getattr(subagent, name)
        for name in ("app", "is_subagent", "history", "tools", "project_dir", "cwd")
        if hasattr(subagent, name)
    }
    # Replace the whole state (client, provider_key, base_url, api_key, ...).
    subagent.__dict__.update(rebuilt.__dict__)
    for name, value in preserved.items():
        setattr(subagent, name, value)


def apply_subagent_role(subagent: Any, role_key: str, project_dir: Optional[str] = None) -> Any:
    """Applies a role definition to a subagent agent.

    Sets role, system prompt, model, and filters tools according to the role
    (excluded delegation/UI tools, read-only/allowed/disallowed lists, and the
    hardened shell description). Shared by invoke_subagent spawn and
    manage_subagent follow-ups so role behavior survives process restarts.
    """
    import copy

    from core.prompt_builder import SUBAGENT_DEFAULT_SYSTEM_PROMPT
    from core.role_registry import RoleRegistry

    registry = RoleRegistry.get_instance()
    registry.load_roles(project_dir=project_dir)
    definition = registry.get_role(role_key)

    # A main-only role must never be used as a subagent type. Fall back to
    # worker so the spawn still produces a usable agent instead of failing.
    if definition.scope == "main":
        definition = registry.get_role("worker")

    # If the role pins a provider, switch the subagent to it. Otherwise inherit
    # the active provider from the parent (the default subagent).
    if definition.provider:
        from core.provider_manager import ProviderManager

        pm = ProviderManager()
        pm.load_providers()
        if not pm.is_provider_connected(definition.provider):
            raise ValueError(
                f"provider '{definition.provider}' for role '{definition.key}' is not connected"
            )
        if getattr(subagent, "provider_key", "") != definition.provider:
            _apply_provider_config(subagent, definition.provider)

    subagent.role = definition.key
    subagent.system_prompt = f"{SUBAGENT_DEFAULT_SYSTEM_PROMPT}\n\n{definition.system_prompt}"
    if definition.model:
        subagent.model = definition.model

    # Disable nested subagent spawning, background task management, and UI questions
    subagent.allow_task = False
    excluded_tools = SUBAGENT_EXCLUDED_TOOLS
    subagent.tools = [
        t
        for t in (getattr(subagent, "tools", None) or [])
        if t.get("function", {}).get("name", "").lower() not in excluded_tools
    ]

    if definition.read_only or definition.disallowed_tools or definition.allowed_tools:
        subagent.tools = [
            t for t in subagent.tools if definition.is_tool_allowed(t.get("function", {}).get("name", "")) is None
        ]

    custom_tools = []
    for t in subagent.tools:
        if isinstance(t, dict) and t.get("function", {}).get("name") == "shell":
            t_copy = copy.deepcopy(t)
            t_copy["function"]["description"] = (
                "Run a synchronous terminal command with a configurable timeout (default 60s, max 300s). "
                "Processes terminate on timeout. Always use non-interactive flags (e.g. -y, --non-interactive) to prevent hanging."
            )
            custom_tools.append(t_copy)
        else:
            custom_tools.append(t)
    subagent.tools = custom_tools
    return definition


def merge_subagent_metrics(subagent: Any, context: Any) -> None:
    """Merges token consumption and cost metrics from subagent into parent app agent."""

    def _val(obj: Any, attr: str, default: Any = 0) -> Any:
        v = getattr(obj, attr, default)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        return default

    if context.app and getattr(context.app, "agent", None):
        main_agent = context.app.agent
        last_in = _val(subagent, "_merged_tokens_input", 0)
        last_out = _val(subagent, "_merged_tokens_output", 0)
        last_tot = _val(subagent, "_merged_total_tokens", 0)
        last_cost = _val(subagent, "_merged_cost_usd", 0.0)

        cur_in = _val(subagent, "tokens_input", 0)
        cur_out = _val(subagent, "tokens_output", 0)
        cur_tot = _val(subagent, "total_tokens", 0)
        cur_cost = _val(subagent, "cost_usd", 0.0)

        delta_in = cur_in - last_in
        delta_out = cur_out - last_out
        delta_tot = cur_tot - last_tot
        delta_cost = cur_cost - last_cost

        if delta_in > 0:
            main_agent.tokens_input = _val(main_agent, "tokens_input", 0) + delta_in
        if delta_out > 0:
            main_agent.tokens_output = _val(main_agent, "tokens_output", 0) + delta_out
        if delta_tot > 0:
            main_agent.total_tokens = _val(main_agent, "total_tokens", 0) + delta_tot
        if delta_cost > 0:
            main_agent.cost_usd = _val(main_agent, "cost_usd", 0.0) + delta_cost

        subagent._merged_tokens_input = cur_in
        subagent._merged_tokens_output = cur_out
        subagent._merged_total_tokens = cur_tot
        subagent._merged_cost_usd = cur_cost


def _safe_save(store: Any, session: AgentSession) -> None:
    """Persist a session without letting a storage OSError escape the background task.

    A failed save must not mark the whole subagent run as errored or blow up the
    task; it is logged and swallowed.
    """
    try:
        store.save(session)
    except Exception:
        pass


async def run_subagent_stream_bg(
    subagent: Any,
    prompt_or_message: str,
    session: AgentSession,
    ctx: Any,
    store: Any,
    cleanup_fn: Optional[Callable[[list], None]] = None,
    error_prefix: str = "Subagent error",
    notification_template: str = "",
    session_id: Optional[str] = None,
    truncate_result: bool = False,
) -> str:
    """Executes a subagent step stream in background with error handling, session finish, cleanup, and UI notifications."""
    acc = [""]
    try:
        async for step in subagent.stream_steps(prompt_or_message):
            record_subagent_step(step, session, acc)
        session.finish(STATUS_COMPLETED)
        _safe_save(store, session)
    except asyncio.CancelledError:
        acc[0] = "[Subagent cancelled]"
        session.finish(STATUS_CANCELLED, "Cancelled by user")
        _safe_save(store, session)
    except Exception as err:
        acc[0] = f"[{error_prefix}: {err}]"
        session.finish(STATUS_ERROR, str(err))
        _safe_save(store, session)
    finally:
        if cleanup_fn:
            try:
                cleanup_fn(acc)
            except Exception:
                pass
        merge_subagent_metrics(subagent, ctx)
        ctx.refresh_status()

        if notification_template:
            sid = session_id or session.id
            if truncate_result:
                from tools.invoke_subagent import _truncate_subagent_result

                result_text = _truncate_subagent_result(acc[0], sid) or "Completed with no text output."
            else:
                result_text = acc[0].strip() or "Completed with no text output."

            msg = notification_template.format(
                session_id=sid,
                result_text=result_text,
                description=session.description,
            )
            ctx.trigger_ai_response(msg)

    return acc[0]


def cancel_running_subagents(store: Any, parent_id: Optional[str] = None) -> int:
    """Cancels running subagent asyncio tasks and marks their sessions cancelled.

    Subagent sessions are the single source of truth for running state, so
    cancellation lives here instead of a parallel in-memory task registry.
    """
    if parent_id:
        sessions = store.get_subagents_for_parent(parent_id)
    else:
        sessions = store.list(kind="subagent")

    cancelled = 0
    for sess in sessions:
        if getattr(sess, "status", "") != "running":
            continue
        async_task = getattr(sess, "async_task", None)
        if async_task and not async_task.done():
            try:
                async_task.cancel()
            except Exception:
                pass
        sess.finish(STATUS_CANCELLED, "Cancelled")
        store.save(sess)
        cancelled += 1
    return cancelled
