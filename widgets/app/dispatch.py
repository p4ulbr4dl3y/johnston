"""Command dispatch layer: registry build + slash-command handler.

Owns building ``COMMAND_REGISTRY`` from ``COMMAND_CLASSES`` and the
``handle_slash_command`` entry point. The command classes stay in
``widgets.commands`` (they are bound to screen imports there); this module only
wires/executes them.

``COMMAND_CLASSES`` is imported lazily to avoid an import cycle (command
classes are bound to screens in ``widgets.commands``); the registry lives here.
"""
from __future__ import annotations

import asyncio
import os

from core.application.skills.manager import get_skill_manager


def _resolve_skills(sm, norm_skill_words):
    """(sync, thread-safe) Resolve slash args into Skill objects; returns (skills, unresolved)."""
    loaded_skills = []
    unresolved = []
    for norm in norm_skill_words:
        skill = sm.get_skill(norm)
        if skill:
            if skill not in loaded_skills:
                loaded_skills.append(skill)
        else:
            unresolved.append(norm)
    return loaded_skills, unresolved


def _load_skill_blocks(loaded_skills) -> list[str]:
    """(sync, thread-safe) Read skill content from disk for the invocation blocks."""
    blocks = []
    for s in loaded_skills:
        content = s.content.strip()
        if not content and s.location and os.path.exists(s.location):
            try:
                with open(s.location, "r", encoding="utf-8") as f:
                    raw_c = f.read()
                from core.infrastructure.runtime.frontmatter import parse_frontmatter

                _, body = parse_frontmatter(raw_c)
                content = body.strip()
            except Exception:
                content = ""
        from core.infrastructure.runtime.xml_utils import escape_xml, escape_xml_attr

        escaped_loc = escape_xml_attr(s.location or "")
        escaped_content = escape_xml(content)
        blocks.append(f'<skill path="{escaped_loc}">\n{escaped_content}\n</skill>')
    return blocks


def build_command_registry() -> dict:
    """Build the name->class registry from the command classes in widgets.commands."""
    from widgets import commands as _commands

    registry = {}
    for cls in _commands.COMMAND_CLASSES:
        registry[cls.name] = cls
        for alias in getattr(cls, "aliases", []):
            registry[alias] = cls
    return registry


COMMAND_REGISTRY = build_command_registry()


async def handle_slash_command(app, command_text: str) -> bool:
    """Executes command if registered or skill found. Returns True if handled."""
    registry = COMMAND_REGISTRY

    if not command_text:
        return False
    words = command_text.strip().split()
    if not words:
        return False

    cmd_name = words[0].lower()

    # Normalization of Cyrillic homoglyphs to Latin (to handle layout errors)
    homoglyphs = {
        "а": "a",
        "в": "b",
        "е": "e",
        "к": "k",
        "м": "m",
        "н": "h",
        "о": "o",
        "р": "p",
        "с": "c",
        "т": "t",
        "у": "y",
        "х": "x",
    }
    normalized_name = "".join(homoglyphs.get(c, c) for c in cmd_name)

    if command_text.strip().startswith("/") and normalized_name in registry:
        cmd_instance = registry[normalized_name]()
        await cmd_instance.execute(app)
        return True

    # Multi-skill & single-skill slash command execution (e.g. /johnston-guide /caveman request)
    other_words = []
    for w in words:
        if not w.startswith("/"):
            other_words.append(w)

    skill_words = [w[1:].lower() for w in words if w.startswith("/")]
    norm_skill_words = ["".join(homoglyphs.get(c, c) for c in raw) for raw in skill_words]
    if norm_skill_words:
        loaded_skills, unresolved = await asyncio.to_thread(_resolve_skills, get_skill_manager(), norm_skill_words)
        other_words.extend(f"/{norm}" for norm in unresolved)
    else:
        loaded_skills = []

    if loaded_skills:
        skill_blocks = await asyncio.to_thread(_load_skill_blocks, loaded_skills)
        skills_content = "\n\n".join(skill_blocks)
        user_request = " ".join(other_words).strip()
        if user_request:
            prompt = f"The following skill(s) have been invoked:\n\n{skills_content}\n\nUser request: {user_request}"
        else:
            prompt = f"The following skill(s) have been invoked:\n\n{skills_content}"

        app.trigger_ai_response(prompt, show_in_ui=True, display_text=command_text)
        return True

    return False
