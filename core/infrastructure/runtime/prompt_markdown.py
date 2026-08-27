"""Markdown assembly for prompt snippets (system-prompt rendering).

Kept in infrastructure so the domain/application layers return structured data
(roles, rules, skills) while a single place owns the rendered Markdown output.
The prompt builder (which by definition assembles the system prompt) is the sole
consumer of these formatters, so the resulting system prompt is unchanged.
"""

import re
from typing import Any, Dict, List

from core.infrastructure.runtime.xml_utils import escape_xml_attr


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

    header = (
        "Skills provide domain-specific instructions and workflows.\n"
        "If a skill is relevant to the user request, you MUST read its SKILL.md using `read` tool before proceeding.\n\n"
        "Available skills:\n"
    )
    return "<skills>\n" + header + "\n".join(items) + "\n</skills>"


def _clean_rule_content(content: str) -> str:
    """Strip trailing whitespace per line and collapse 3+ consecutive newlines."""
    if not content:
        return ""
    lines = [line.rstrip() for line in content.strip().splitlines()]
    cleaned = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def format_rules_markdown(rules: List[Any]) -> str:
    """Build the unified ``<user_rules>`` block for the system prompt."""
    if not rules:
        return ""

    def _sort_key(r: Any) -> tuple:
        source = getattr(r, "source", "global")
        name = getattr(r, "name", str(r))
        priority = 0 if source == "global" else 1
        return (priority, str(name).lower())

    sorted_rules = sorted(rules, key=_sort_key)
    items = []
    for r in sorted_rules:
        r_name = getattr(r, "name", str(r))
        r_source = getattr(r, "source", "global")
        r_content = _clean_rule_content(getattr(r, "content", ""))
        if not r_content:
            continue
        rule_id = escape_xml_attr(f"{r_source}:{r_name}")
        items.append(f'<rule id="{rule_id}">\n{r_content}\n</rule>')

    if not items:
        return ""

    header = "User rules (strict priority: project > global > defaults):\n"
    return f"<user_rules>\n{header}" + "\n".join(items) + "\n</user_rules>"


def format_subagents_markdown(roles: List[Any]) -> str:
    """Build the ``<subagents>`` block for the system prompt from role objects."""
    if not roles:
        return ""

    items = []
    for role in roles:
        meta_parts = []
        if getattr(role, "allowed_tools", None):
            meta_parts.append(f"tools: {', '.join(role.allowed_tools)}")
        if getattr(role, "provider", None):
            meta_parts.append(f"provider: {role.provider}")
        meta_str = f" ({', '.join(meta_parts)})" if meta_parts else ""
        desc = getattr(role, "description", "") or ""
        desc_clean = " ".join(desc.split()) if desc else ""
        desc_str = f": {desc_clean}" if desc_clean else ""
        r_key = getattr(role, "key", str(role))
        items.append(f"- {r_key}{meta_str}{desc_str}")

    header = (
        "Delegate bounded tasks to background subagents via `invoke_subagent`.\n\n"
        "Guidelines:\n"
        "- Worktree Isolation: Pass `branch='<feature>'` for code edits to run in an isolated Git worktree and avoid file conflicts.\n"
        "- Reuse Context: Use `manage_subagent(action='send_message', session_id=...)` to continue an existing subagent rather than spawning new ones.\n"
        "- Reactive: Completion notifies automatically. Do NOT poll status in a loop; proceed with other work or end turn.\n"
        "- Subagents cannot spawn subagents or ask user questions.\n\n"
        "Available roles:\n"
    )
    return "<subagents>\n" + header + "\n".join(items) + "\n</subagents>"


def format_mcp_servers_markdown(by_server: Dict[str, List[str]]) -> str:
    """Build the ``<mcp_servers>`` block for the system prompt from server->tools mapping."""
    if not by_server:
        return ""

    items = []
    for server in sorted(by_server):
        tools = by_server[server]
        if not tools:
            continue
        tools_str = ", ".join(sorted(tools))
        items.append(f"- {server}: {tools_str}")

    if not items:
        return ""

    header = "External tools provided by Model Context Protocol (MCP) servers:\n"
    return f"<mcp_servers>\n{header}" + "\n".join(items) + "\n</mcp_servers>"



