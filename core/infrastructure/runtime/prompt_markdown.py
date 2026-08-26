"""Markdown assembly for prompt snippets (system-prompt rendering).

Kept in infrastructure so the domain/application layers return structured data
(roles, rules, skills) while a single place owns the rendered Markdown output.
The prompt builder (which by definition assembles the system prompt) is the sole
consumer of these formatters, so the resulting system prompt is unchanged.
"""

from typing import Any, List


def format_skills_markdown(skills: List[Any]) -> str:
    """Build the ``## Skills`` block for the system prompt from skill objects.

    ``skills`` are structured ``Skill`` objects (name/description/scope attrs);
    accepts any object exposing those attributes so the infrastructure formatter
    stays decoupled from the application layer. Returns ``""`` when there are no
    skills. Produces the exact Markdown shape previously emitted by the
    SkillManager.
    """
    if not skills:
        return ""

    global_skills = []
    project_skills = []

    for s in skills:
        desc = f": {s.description}" if s.description else ""
        line = f"- `{s.name}`{desc}"
        scope_val = getattr(s.scope, "value", s.scope)
        if scope_val == "project":
            project_skills.append(line)
        else:
            global_skills.append(line)

    lines = ["## Skills (read SKILL.md on user request or trigger)"]

    if global_skills:
        lines.append("\n### Global (`~/.johnston/skills/<name>/SKILL.md`)")
        lines.extend(global_skills)

    if project_skills:
        lines.append("\n### Project (`.johnston/skills/<name>/SKILL.md`)")
        lines.extend(project_skills)

    return "\n".join(lines)


def format_rules_markdown(rules: List[Any]) -> str:
    """Build the ``<rules>`` block for the system prompt.

    ``rules`` is the ordered list of active ``RuleDefinition`` objects (the
    application layer filters by role and returns data). Returns ``""`` when
    there are no matching rules.
    """
    if not rules:
        return ""

    matching = []
    for r in rules:
        matching.append(f'<rule name="{r.name}">\n{r.content}\n</rule>')

    return "<rules>\n" + "\n\n".join(matching) + "\n</rules>"
