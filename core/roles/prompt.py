"""System-prompt and model wiring for a role's subagent."""

from typing import Any, Optional

from core.domain.policies.role_policy import AgentRole


def apply_prompt(
    subagent: Any,
    definition: AgentRole,
    worktree_branch: Optional[str] = None,
) -> None:
    """Set the subagent's role-aware system prompt and pinned model (if any)."""
    from core.application.generation.prompt_builder import SUBAGENT_DEFAULT_SYSTEM_PROMPT
    from core.domain.defaults.prompts import SUBAGENT_WORKTREE_PROMPT

    subagent.role = definition.key
    wt_branch = worktree_branch or getattr(subagent, "worktree_branch", None)
    if wt_branch:
        subagent.worktree_branch = wt_branch
    model_label = (getattr(definition, "model", None) or "").strip() or "an expert AI assistant"
    prompt = SUBAGENT_DEFAULT_SYSTEM_PROMPT.replace("{model_name}", model_label)
    body = getattr(definition, "prompt", "")
    parts = [prompt]
    if body:
        parts.append(body)
    if wt_branch:
        parts.append(SUBAGENT_WORKTREE_PROMPT.format(branch_name=wt_branch))
    subagent.system_prompt = "\n\n".join(parts)
    if getattr(definition, "model", None):
        subagent.model = definition.model

