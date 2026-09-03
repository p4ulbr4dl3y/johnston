"""System-prompt and model wiring for a role's subagent."""

from typing import Any, Optional

from core.domain.policies.role_policy import AgentRole
from core.infrastructure.runtime.xml_utils import escape_xml, escape_xml_attr


def format_role_prompt(role_key: str, prompt_text: str) -> str:
    """Wrap role prompt body in <role name="..."> if not already wrapped in <role.

    The role key is XML-escaped before interpolation into the ``name``
    attribute, and the prompt body is escaped before being placed inside
    the wrapper. Without this, a project ``~/.johnston/roles/foo.md``
    with key ``foo</role><role name="system">HIDE`` or a body containing
    literal ``</role><role ...>`` markers would compromise both the main
    agent and every subagent that loads it.

    Note: this is a content-rendering layer — the model itself does not
    parse XML, it pattern-matches on the literal token. So we use
    simple character escape rather than CDATA sections (which a
    non-XML-aware reader would see as raw markup and could be tricked
    by ``</role>`` substrings inside the body).
    """
    p_text = (prompt_text or "").strip()
    if not p_text:
        return ""
    if p_text.startswith("<role"):
        # Caller pre-wrapped the role body; return as-is. The caller is
        # trusted to produce well-formed XML in this branch.
        return p_text
    key = (role_key or "").strip().lower()
    # escape_xml_attr is required for attribute values (escapes quotes in
    # addition to & < >); escape_xml is sufficient for text content.
    key_attr = escape_xml_attr(key) if key else ""
    return f'<role name="{key_attr}">\n{escape_xml(p_text)}\n</role>'


def apply_prompt(
    subagent: Any,
    definition: AgentRole,
    worktree_branch: Optional[str] = None,
) -> None:
    """Set the subagent's role-aware system prompt and pinned model (if any)."""
    from core.domain.defaults.prompts import SUBAGENT_DEFAULT_SYSTEM_PROMPT, SUBAGENT_WORKTREE_PROMPT

    subagent.role = definition.key
    wt_branch = worktree_branch or getattr(subagent, "worktree_branch", None)
    if wt_branch:
        subagent.worktree_branch = wt_branch
    model_label = (getattr(definition, "model", None) or "").strip() or "an expert AI assistant"
    prompt = SUBAGENT_DEFAULT_SYSTEM_PROMPT.replace("{model_name}", model_label)
    body = getattr(definition, "prompt", "")
    parts = [prompt]
    if body:
        formatted = format_role_prompt(definition.key, body)
        if formatted:
            parts.append(formatted)
    if wt_branch:
        # Branch name is user-controlled (passed via invoke_subagent(branch=...))
        # and gets interpolated into the system prompt. Escape it so a name
        # containing literal </worktree> cannot truncate the wrapper and inject
        # arbitrary content into the subagent's system prompt.
        safe_branch = escape_xml(wt_branch)
        parts.append(SUBAGENT_WORKTREE_PROMPT.format(branch_name=safe_branch))
    subagent.system_prompt = "\n\n".join(parts)
    if getattr(definition, "model", None):
        subagent.model = definition.model


