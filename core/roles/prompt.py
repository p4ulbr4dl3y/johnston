"""System-prompt and model wiring for a role's subagent."""

from typing import Any

from core.domain.policies.role_policy import AgentRole


def apply_prompt(subagent: Any, definition: AgentRole) -> None:
    """Set the subagent's role-aware system prompt and pinned model (if any)."""
    from core.application.generation.prompt_builder import SUBAGENT_DEFAULT_SYSTEM_PROMPT

    subagent.role = definition.key
    model_label = (getattr(definition, "model", None) or "").strip() or "an expert AI assistant"
    prompt = SUBAGENT_DEFAULT_SYSTEM_PROMPT.replace("{model_name}", model_label)
    body = getattr(definition, "prompt", "")
    subagent.system_prompt = f"{prompt}\n\n{body}"
    if getattr(definition, "model", None):
        subagent.model = definition.model
