"""Markdown assembly for prompt snippets (system-prompt rendering).

Kept in infrastructure so the domain/application layers return structured data
(roles, rules, skills) while a single place owns the rendered Markdown output.
The prompt builder (which by definition assembles the system prompt) is the sole
consumer of these formatters, so the resulting system prompt is unchanged.

Conventions for token-efficient snippets:
- One-line header summarizing scope; rules enumerated tersely.
- `<tag>...</tag>` wrapping so the model can extract sections by tag-name.
- Higher-priority content FIRST so prompt-cache prefix is stable across inputs.
- No examples in prompt (they are in the system prompt's <contract> section).
"""

import re
from typing import Any, Dict, List

from core.infrastructure.runtime.xml_utils import escape_xml, escape_xml_attr

# ---- Skills ----------------------------------------------------------------

def format_skills_markdown(skills: List[Any]) -> str:
    """Build the ``<skills>`` block for the system prompt from skill objects.

    Token-efficient: bullet list, name + path + 1-line desc, no prose header.
    Skills sorted by priority (project > global > bundled) so overrides win.
    """
    if not skills:
        return ""

    def _sort_key(s: Any) -> tuple:
        scope = getattr(s, "scope", None)
        scope_val = getattr(scope, "value", scope) if scope is not None else None
        scope_str = str(scope_val).lower() if scope_val is not None else ""
        if scope_str in ("project", "project_dir"):
            priority = 0
        elif scope_str == "global":
            priority = 1
        elif scope_str in ("bundled", "builtin", "default"):
            priority = 2
        else:
            priority = 1
        return (priority, str(getattr(s, "name", "")).lower())

    sorted_skills = sorted(skills, key=_sort_key)
    items = []
    for s in sorted_skills:
        loc = getattr(s, "location", None) or getattr(s, "path", None)
        # XML-escape user-supplied fields (name, path, description) before
        # interpolation. A skill description containing literal
        # `</skills><system_note>...` would otherwise truncate the
        # wrapper and inject synthetic-looking markup.
        name_safe = escape_xml(getattr(s, "name", "") or "")
        loc_safe = escape_xml(str(loc)) if loc else ""
        path_part = f" ({loc_safe})" if loc_safe else ""
        desc = getattr(s, "description", "") or ""
        desc_clean = " ".join(desc.split()) if desc else ""
        desc_part = f": {escape_xml(desc_clean)}" if desc_clean else ""
        items.append(f"- {name_safe}{path_part}{desc_part}")

    header = (
        "Skills: read SKILL.md via `read` if relevant. Project overrides global overrides bundled.\n"
    )
    return "<skills>\n" + header + "\n".join(items) + "\n</skills>"


# ---- Rules ------------------------------------------------------------------

def _clean_rule_content(content: str) -> str:
    """Strip trailing whitespace per line and collapse 3+ consecutive newlines."""
    if not content:
        return ""
    lines = [line.rstrip() for line in content.strip().splitlines()]
    cleaned = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def format_rules_markdown(rules: List[Any]) -> str:
    """Build the unified ``<user_rules>`` block.

    BUGFIX: previously sorted global-first which contradicted the
    "project > global" header. Now sorts project-first (priority 0),
    so a later rule never silently overrides an earlier one when they
    conflict (overrides apply "later wins" by LLM convention, so
    higher-priority content must come FIRST).
    """
    if not rules:
        return ""

    def _sort_key(r: Any) -> tuple:
        source = getattr(r, "source", "global")
        name = getattr(r, "name", str(r))
        # Priority: project=0 (FIRST), global=1, default=2
        priority = {"project": 0, "global": 1}.get(source, 2)
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
        # Escape rule body (not CDATA) for consistency with skills/subagents/
        # mcp_servers — the model is a non-XML-aware reader, it pattern-matches
        # on the literal token, so entity-encoded &lt; provides the same
        # wrapper integrity without the visual confusion of CDATA tags inside
        # rule body. CDATA would still leave the literal close-tag visible
        # to the model, defeating the purpose.
        items.append(f'<rule id="{rule_id}">\n{escape_xml(r_content)}\n</rule>')

    if not items:
        return ""

    header = "User rules. Higher-priority rules appear FIRST and override lower-priority rules on conflict. Order: project > global > defaults.\n"
    return f"<user_rules>\n{header}" + "\n".join(items) + "\n</user_rules>"


# ---- Subagents --------------------------------------------------------------

def format_subagents_markdown(roles: List[Any], max_concurrent: int = 5) -> str:
    """Build the ``<subagents>`` block from role objects.

    Token-efficient: terse rules + bullet list of available roles.
    ``max_concurrent`` is injected from runtime config so the model can
    budget parallel work without guessing.
    """
    if not roles:
        return ""

    items = []
    for role in roles:
        meta_parts = []
        if getattr(role, "allowed_tools", None):
            meta_parts.append(f"tools: {', '.join(escape_xml(t) for t in role.allowed_tools)}")
        if getattr(role, "provider", None) and getattr(role, "model", None):
            meta_parts.append(f"model: {escape_xml(role.provider)}/{escape_xml(role.model)}")
        elif getattr(role, "provider", None):
            meta_parts.append(f"provider: {escape_xml(role.provider)}")
        elif getattr(role, "model", None):
            meta_parts.append(f"model: {escape_xml(role.model)}")
        if getattr(role, "read_only", False):
            meta_parts.append("read-only")
        meta_str = f" ({', '.join(meta_parts)})" if meta_parts else ""
        desc = getattr(role, "description", "") or ""
        desc_clean = " ".join(desc.split()) if desc else ""
        desc_str = f": {escape_xml(desc_clean)}" if desc_clean else ""
        r_key = getattr(role, "key", str(role))
        items.append(f"- {escape_xml(r_key)}{meta_str}{desc_str}")

    header = (
        "Delegate bounded tasks via `invoke_subagent` (background; auto-notify on completion).\n"
        "Rules:\n"
        "- threshold: do atomic/routine tasks directly. Delegate to subagents ONLY when work is: parallelizable, requires isolation, or large (≥3-5 steps).\n"
        "- title: noun phrase in English, 3-5 words (e.g. 'Auth token refactor'), not verbs.\n"
        "- prompt: include acceptance criteria, relative file paths, expected output format.\n"
        "- isolation: write roles (e.g. worker) auto-isolate in a git worktree on an auto-generated branch. Read-only roles (e.g. explorer) run in the main workspace.\n"
        "- merge: on subagent completion, notification provides branch name; parent MUST inspect diff and run `git merge <branch>`.\n"
        f"- concurrency: ≤{max_concurrent} parallel. Hit limit → wait for completion notifications before spawning more; do NOT poll list.\n"
        "- follow-up: use `manage_subagent(send_message, session_id=...)` for refinements, fixes on partial/blocked tasks, or next steps in same scope (restores worktree + history). Spawn NEW subagent for independent tasks or different roles.\n"
        "- reactive: execution automatically pauses and resumes with <notification> when subagents finish. NEVER poll `list` in a loop; stop calling tools to wait.\n"
        "- limits: subagents cannot call `invoke_subagent`/`manage_subagent`/`manage_shell`/`ask_user`, cannot run background processes, cannot ask the user. Decisions needing the user go in the subagent's report.\n"
        "- cost: subagent tokens/cost merge into this session's totals on completion.\n\n"
        "Available roles:\n"
    )
    return "<subagents>\n" + header + "\n".join(items) + "\n</subagents>"


# ---- MCP servers ------------------------------------------------------------

def format_mcp_servers_markdown(by_server: Dict[str, List[str]]) -> str:
    """Build the ``<mcp_servers>`` block. Lists server→tools for name-disambiguation.

    Token-efficient: one line per server. Schema details (params, descriptions)
    come from the function definitions themselves; this block only adds
    server-to-tool grouping AND the namespace rule for collisions.
    """
    if not by_server:
        return ""

    items = []
    for server in sorted(by_server):
        tools = by_server[server]
        if not tools:
            continue
        # Escape server and tool names — an MCP server name containing
        # literal `</mcp_servers>` would otherwise terminate the wrapper
        # early and inject arbitrary content as a system-level block.
        tools_str = ", ".join(escape_xml(t) for t in sorted(tools))
        items.append(f"- {escape_xml(server)}: {tools_str}")

    if not items:
        return ""

    header = (
        "MCP tools. Schemas are in the function definitions. On name collisions, call as `server__tool`.\n"
    )
    return f"<mcp_servers>\n{header}" + "\n".join(items) + "\n</mcp_servers>"
