"""Markdown assembly for prompt snippets (system-prompt rendering).

Kept in infrastructure so the domain/application layers return structured data
(roles, rules, skills) while a single place owns the rendered Markdown output.
The prompt builder (which by definition assembles the system prompt) is the sole
consumer of these formatters, so the resulting system prompt is unchanged.
"""

from typing import Any, List


def format_skills_markdown(skills: List[Any]) -> str:
    """Build the ``<skills>`` block for the system prompt from skill objects.

    ``skills`` are structured ``Skill`` objects (name/description/scope attrs);
    accepts any object exposing those attributes so the infrastructure formatter
    stays decoupled from the application layer. Returns ``""`` when there are no
    skills.
    """
    if not skills:
        return ""

    from core.infrastructure.runtime.xml_utils import escape_xml_attr

    skills_xml = []
    for s in skills:
        scope_val = getattr(s.scope, "value", s.scope)
        attrs = [f'name="{escape_xml_attr(s.name)}"', f'scope="{escape_xml_attr(str(scope_val))}"']
        loc = getattr(s, "location", None) or getattr(s, "path", None)
        if loc:
            attrs.append(f'path="{escape_xml_attr(str(loc))}"')
        if s.description:
            attrs.append(f'desc="{escape_xml_attr(s.description)}"')
        skills_xml.append(f"  <skill {' '.join(attrs)}/>")

    return "<skills>\n" + "\n".join(skills_xml) + "\n</skills>"


def format_rules_markdown(rules: List[Any]) -> str:
    """Build the ``<rules>`` block for the system prompt.

    ``rules`` is the ordered list of active ``RuleDefinition`` objects (the
    application layer filters by role and returns data). Returns ``""`` when
    there are no matching rules.
    """
    if not rules:
        return ""

    from core.infrastructure.runtime.xml_utils import escape_xml, escape_xml_attr

    matching = []
    for r in rules:
        r_name = escape_xml_attr(getattr(r, "name", str(r)))
        r_content = escape_xml(getattr(r, "content", ""))
        matching.append(f'<rule name="{r_name}">\n{r_content}\n</rule>')

    return "<rules>\n" + "\n\n".join(matching) + "\n</rules>"
