"""Agent configuration and metric merging for subagent streaming."""

from typing import Any, Optional

from johnston.core.domain.entities.session import AgentSession


def sync_session_metrics(session: AgentSession, agent: Any) -> None:
    """Copy token/cost metrics from the live agent onto its session record."""
    for attr in ("tokens_input", "tokens_output", "total_tokens", "cost_usd", "last_context_tokens"):
        setattr(session, attr, getattr(agent, attr, getattr(session, attr)))


_sync_subagent_metrics = sync_session_metrics


def configure_agent(
    agent: Any,
    role_key: str = "worker",
    app: Any = None,
    project_dir: Optional[str] = None,
    is_subagent: bool = False,
    worktree_branch: Optional[str] = None,
) -> Any:
    """Configures an agent (main or subagent): binds the app, marks role & subagent flag,
    sets limits/sandbox, and applies role definitions (system prompt, model, tool filtering).
    """
    agent.app = app
    agent.is_subagent = is_subagent
    agent.preserve_root_prompt = is_subagent
    if is_subagent:
        from johnston.core.infrastructure.config.settings import get_settings

        agent.auto_compact_token_limit = get_settings().subagents.auto_compact_token_limit
        if worktree_branch:
            agent.worktree_branch = worktree_branch
    if app and hasattr(app, "sandbox_enabled"):
        agent.sandbox_enabled = app.sandbox_enabled
    from johnston.core.application.roles import apply_role

    return apply_role(
        agent,
        role_key,
        project_dir=project_dir,
        worktree_branch=worktree_branch,
        is_subagent=is_subagent,
    )


def configure_subagent_agent(
    subagent: Any,
    role_key: str,
    app: Any = None,
    project_dir: Optional[str] = None,
    worktree_branch: Optional[str] = None,
) -> Any:
    """Configures a subagent agent: binds the app, marks it as a subagent, and
    applies its role (system prompt, model, tool filtering).

    Shared by invoke_subagent spawn and message_subagent follow-ups so the setup
    stays identical (and survives process restarts in the follow-up path).
    """
    return configure_agent(
        subagent,
        role_key=role_key,
        app=app,
        project_dir=project_dir,
        is_subagent=True,
        worktree_branch=worktree_branch,
    )


def merge_subagent_metrics(subagent: Any, context: Any) -> None:
    """Merges token consumption and cost metrics from subagent into parent app agent."""

    def _val(obj: Any, attr: str, default: Any = 0) -> Any:
        v = getattr(obj, attr, default)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        return default

    if context.host and getattr(context.host, "agent", None):
        main_agent = context.host.agent
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
