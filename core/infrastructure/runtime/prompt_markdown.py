"""Markdown assembly for prompt snippets (system-prompt rendering).

Kept in infrastructure so the domain/application layers return structured data
(roles, rules, skills) while a single place owns the rendered Markdown output.
The prompt builder (which by definition assembles the system prompt) is the sole
consumer of these formatters, so the resulting system prompt is unchanged.
"""

from typing import Any, List


def format_skills_markdown(skills: List[Any]) -> str:
    """Build the ``<skills>`` block for the system prompt from skill objects."""
    if not skills:
        return ""

    items = []
    for s in skills:
        loc = getattr(s, "location", None) or getattr(s, "path", None)
        path_part = f" ({loc})" if loc else ""
        desc = getattr(s, "description", "") or ""
        desc_clean = " ".join(desc.split()) if desc else ""
        desc_part = f": {desc_clean}" if desc_clean else ""
        items.append(f"- {s.name}{path_part}{desc_part}")

    header = "To activate a skill, read its SKILL.md using `read` tool.\n\n"
    return "<skills>\n" + header + "\n".join(items) + "\n</skills>"


def format_rules_markdown(rules: List[Any]) -> str:
    """Build the ``<user_rules>`` block for the system prompt."""
    if not rules:
        return ""

    items = []
    for r in rules:
        r_name = getattr(r, "name", str(r))
        r_content = getattr(r, "content", "").strip()
        items.append(f"- {r_name}: {r_content}")

    return "<user_rules>\n" + "\n".join(items) + "\n</user_rules>"
