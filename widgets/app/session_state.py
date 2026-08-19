"""Session state collection helpers for widgets.

Pure aggregators that read session/agent state via ``app`` and return ready
data (or recomputed context-token estimates). The mixin keeps the store writes
and UI-render/restore flow.
"""
from __future__ import annotations

from typing import Any, Optional

from widgets.utils.message_visibility import is_ui_visible_user_message


def collect_session_data(app: Any) -> Optional[dict]:
    """Collect session data from the transcript session store (source of truth).

    The transcript (``app.sm`` session .messages) is maintained on the SDK side
    via ``record_subagent_step`` during generation, so persistence no longer reads
    widget state. Title is derived from the first user message in the transcript.
    """
    session = app.sm.get(app.current_session_id, reload=False)
    if not session:
        return None

    messages = list(session.messages)

    title = ""
    for msg in messages:
        if isinstance(msg, dict) and msg.get("type") == "user" and is_ui_visible_user_message(msg):
            first_msg = msg.get("text", "")
            title = first_msg[:30] + "..." if len(first_msg) > 30 else first_msg
            break
    if not title:
        return None

    agent_history = getattr(app.agent, "history", [])

    return {
        "id": app.current_session_id,
        "title": title,
        "messages": messages,
        "agent_history": agent_history,
        "tokens_input": getattr(app.agent, "tokens_input", 0),
        "tokens_output": getattr(app.agent, "tokens_output", 0),
        "total_tokens": getattr(app.agent, "total_tokens", 0),
        "cost_usd": getattr(app.agent, "cost_usd", 0.0),
        "last_context_tokens": getattr(app.agent, "last_context_tokens", 0),
    }


def recompute_context_tokens(agent: Any, ctx: int) -> int:
    """Recompute the context-token estimate when a session has none recorded.

    Returns the current ``ctx`` unless the session tracked none and the agent has
    history, in which case it recomputes from the system prompt, tools and history.
    """
    if ctx or not getattr(agent, "history", []):
        return ctx

    from core.application.generation.prompt_builder import PromptBuilder
    from core.infrastructure.runtime.token_util import estimate_tokens

    is_subagent = getattr(agent, "is_subagent", False)
    builder = PromptBuilder(
        agent.system_prompt,
        agent.tools,
        role=getattr(agent, "role", "worker"),
        is_subagent=is_subagent,
        subagent_schema=getattr(agent, "subagent_schema", None),
    )
    sys_prompt = builder.build_system_prompt()
    all_tools = builder.build_tools()
    return estimate_tokens(sys_prompt) + estimate_tokens(all_tools) + estimate_tokens(agent.history)
