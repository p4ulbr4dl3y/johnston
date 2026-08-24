"""System-prompt and model wiring for a role's subagent."""


def apply_prompt(subagent, definition) -> None:
    """Set the subagent's role-aware system prompt and pinned model (if any)."""
    from core.application.generation.prompt_builder import SUBAGENT_DEFAULT_SYSTEM_PROMPT

    subagent.role = definition.key
    model_label = (getattr(definition, "model", None) or "").strip() or "an expert AI assistant"
    prompt = SUBAGENT_DEFAULT_SYSTEM_PROMPT.replace("{model_name}", model_label)
    if "{scratch_dir}" in prompt:
        s_dir = getattr(subagent, "scratch_dir", None)
        if not isinstance(s_dir, str) or not s_dir.strip():
            try:
                from core.session_manager import SessionStore

                sess_id = getattr(subagent, "session_id", None)
                safe_id = sess_id if isinstance(sess_id, str) and sess_id.strip() else "subagent"
                s_dir = SessionStore.get_instance().get_scratch_dir(safe_id)
            except Exception:
                s_dir = "/tmp"
        prompt = prompt.replace("{scratch_dir}", str(s_dir))
    body = getattr(definition, "prompt", "")
    subagent.system_prompt = f"{prompt}\n\n{body}"
    if getattr(definition, "model", None):
        subagent.model = definition.model
