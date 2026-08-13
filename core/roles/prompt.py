"""System-prompt and model wiring for a role's subagent."""


def apply_prompt(subagent, definition) -> None:
    """Set the subagent's role-aware system prompt and pinned model (if any)."""
    from core.prompt_builder import SUBAGENT_DEFAULT_SYSTEM_PROMPT

    subagent.role = definition.key
    subagent.system_prompt = f"{SUBAGENT_DEFAULT_SYSTEM_PROMPT}\n\n{definition.system_prompt}"
    if definition.model:
        subagent.model = definition.model
