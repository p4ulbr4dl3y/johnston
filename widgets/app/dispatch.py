"""Command dispatch layer: registry build + slash-command handler.

Owns building ``COMMAND_REGISTRY`` from ``COMMAND_CLASSES`` and the
``handle_slash_command`` entry point. The command classes stay in
``widgets.commands`` (they are bound to screen imports there); this module only
wires/executes them.

To avoid an import cycle (``widgets.commands`` re-exports the registry/handler
from here after binding ``COMMAND_CLASSES``), ``COMMAND_CLASSES`` is imported
lazily, and the registry is read from ``widgets.commands`` at handle time so
tests patching ``widgets.commands.COMMAND_REGISTRY`` keep working.
"""
from __future__ import annotations

import asyncio
import os

from core.application.skills.manager import SkillManager


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
    from widgets import commands as _commands

    # Read registry from widgets.commands so patches against that name apply here.
    registry = _commands.COMMAND_REGISTRY

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
    words = command_text.strip().split()
    sm = SkillManager()
    loaded_skills = []
    other_words = []

    for w in words:
        if w.startswith("/"):
            raw_sname = w[1:].lower()
            norm_sname = "".join(homoglyphs.get(c, c) for c in raw_sname)
            skill = sm.get_skill(norm_sname)
            if skill:
                if skill not in loaded_skills:
                    loaded_skills.append(skill)
            else:
                other_words.append(w)
        else:
            other_words.append(w)

    if loaded_skills:
        skill_blocks = []
        for s in loaded_skills:
            content = s.get("content", "").strip()
            if not content and s.get("location") and os.path.exists(s["location"]):
                try:
                    with open(s["location"], "r", encoding="utf-8") as f:
                        raw_c = f.read()
                    from core.application.skills.manager import parse_frontmatter

                    _, body = parse_frontmatter(raw_c)
                    content = body.strip()
                except Exception:
                    content = ""
            skill_blocks.append(f'<SKILL path="{s.get("location", "")}">\n{content}\n</SKILL>')

        skills_content = "\n\n".join(skill_blocks)
        user_request = " ".join(other_words).strip()
        if user_request:
            prompt = f"The following skill(s) have been invoked:\n\n{skills_content}\n\nUser request: {user_request}"
        else:
            prompt = f"The following skill(s) have been invoked:\n\n{skills_content}"

        try:
            from widgets.chat_view import ChatView

            chat_view = app.query_one(ChatView)

            asyncio.create_task(chat_view.add_user_message(command_text))
            app.trigger_ai_response(prompt, show_in_ui=False)
        except Exception:
            app.trigger_ai_response(prompt, show_in_ui=True)
        return True

    return False
