"""Command/skill suggestion collection for the command suggestions widget.

Pulls the list of registered slash commands (from the command registry) plus
skill-derived commands (from the skill manager) with a 10s TTL cache. The
widget keeps rendering/search/filtering and delegates list building here.
"""
from __future__ import annotations

import time

from core.application.skills.manager import SkillManager
from widgets.app.dispatch import COMMAND_REGISTRY

_command_suggestions_cache: list[tuple[str, str]] = []
_command_suggestions_cache_time: float = 0.0


def get_all_command_suggestions() -> list[tuple[str, str]]:
    """Gets list of (command_name, description) for registered commands and skills with 10s cache."""
    global _command_suggestions_cache, _command_suggestions_cache_time
    now = time.time()
    if _command_suggestions_cache and (now - _command_suggestions_cache_time < 10.0):
        return _command_suggestions_cache

    suggestions = []
    registered = set()

    for name, cmd in COMMAND_REGISTRY.items():
        desc = cmd.description if name == cmd.name else f"Alias for {cmd.name}"
        suggestions.append((name, desc))
        registered.add(name)

    try:
        sm = SkillManager()
        skills = sm.list_skills()
        for s in skills:
            s_cmd = f"/{s.name}"
            if s_cmd not in registered:
                desc = f"Skill: {s.description}" if s.description else f"Skill: {s.name}"
                suggestions.append((s_cmd, desc))
                registered.add(s_cmd)
    except Exception:
        pass

    _command_suggestions_cache = suggestions
    _command_suggestions_cache_time = now
    return suggestions
