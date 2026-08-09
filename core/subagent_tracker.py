"""Subagent streaming helpers operating on the unified AgentSession model.

The SubagentTracker singleton and SubagentSessionData class are gone: subagent
sessions are AgentSession records (kind="subagent") stored per-project under
sessions/<parent_id>.subagents/ via SessionStore.
"""

import asyncio
from typing import Any, Callable, Optional

from core.session_manager import STATUS_CANCELLED, STATUS_COMPLETED, STATUS_ERROR, AgentSession


def record_subagent_step(step: tuple, session: AgentSession, text_accumulator: list) -> None:
    """Records a subagent execution step event into the session message history."""
    import math

    etype = step[0]
    val1 = step[1] if len(step) > 1 else ""
    val2 = step[2] if len(step) > 2 else ""
    val3 = step[3] if len(step) > 3 else None

    if etype == "thinking_start":
        session.add_event({"type": "thinking_start", "val1": val1})
    elif etype == "thinking_delta":
        session.add_event({"type": "thinking_delta", "val1": val1})
    elif etype == "thinking_end":
        try:
            dur = float(val1)
            if not math.isfinite(dur):
                dur = 0.0
        except (ValueError, TypeError):
            dur = 0.0
        session.add_event({"type": "thinking_end", "duration": dur, "content": val2})
    elif etype == "tool":
        targs = val3 if isinstance(val3, dict) else {}
        session.add_event({"type": "tool", "tool_type": val1, "target": val2, "args": targs})
    elif etype == "tool_result":
        session.add_event({"type": "tool_result", "result_text": val1})
    elif etype == "bot_chunk":
        session.add_event({"type": "bot_chunk", "text": val1})
        text_accumulator[0] += val1
    elif etype == "bot_delta":
        session.add_event({"type": "bot_delta", "text": val1})
        text_accumulator[0] = val1
    elif etype in ("bot_text", "outro"):
        session.add_event({"type": "bot_text", "text": val1})
        text_accumulator[0] = val1


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


async def run_subagent_stream_bg(
    subagent: Any,
    prompt_or_message: str,
    session: AgentSession,
    ctx: Any,
    store: Any,
    cleanup_fn: Optional[Callable[[list], None]] = None,
    error_prefix: str = "Subagent error",
    notification_template: str = "",
    task_id: Optional[str] = None,
    truncate_result: bool = False,
) -> str:
    """Executes a subagent step stream in background with error handling, session finish, cleanup, and UI notifications."""
    acc = [""]
    try:
        async for step in subagent.stream_steps(prompt_or_message):
            record_subagent_step(step, session, acc)
        session.finish(STATUS_COMPLETED)
        store.save(session)
    except asyncio.CancelledError:
        acc[0] = "[Subagent cancelled]"
        session.finish(STATUS_CANCELLED, "Cancelled by user")
        store.save(session)
    except Exception as err:
        acc[0] = f"[{error_prefix}: {err}]"
        session.finish(STATUS_ERROR, str(err))
        store.save(session)
    finally:
        if cleanup_fn:
            cleanup_fn(acc)
        merge_subagent_metrics(subagent, ctx)
        if task_id and ctx.background_tasks:
            for t in ctx.background_tasks:
                if getattr(t, "task_id", "") == task_id:
                    t.is_running = False

        ctx.refresh_status()

        if notification_template:
            tid = task_id or session.id
            if truncate_result:
                from tools.invoke_subagent import _truncate_subagent_result
                result_text = _truncate_subagent_result(acc[0], tid) or "Completed with no text output."
            else:
                result_text = acc[0].strip() or "Completed with no text output."

            msg = notification_template.format(
                task_id=tid,
                result_text=result_text,
                description=session.description,
            )
            ctx.trigger_ai_response(msg)

    return acc[0]
