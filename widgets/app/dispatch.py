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
        from core.infrastructure.runtime.xml_utils import escape_xml_attr

        escaped_name = escape_xml_attr(s.name or "")
        path_attr = f' path="{escape_xml_attr(s.location)}"' if s.location else ""
        blocks.append(f'<skill name="{escaped_name}"{path_attr}>\n{content}\n</skill>')
    return blocks


def build_command_registry() -> dict:
    """Build the name->class registry from the command classes in widgets.presentation.commands."""
    from widgets.presentation.commands import COMMAND_CLASSES

    registry = {}
    for cls in COMMAND_CLASSES:
        registry[cls.name] = cls
        for alias in getattr(cls, "aliases", []):
            registry[alias] = cls
    return registry


COMMAND_REGISTRY = build_command_registry()


async def handle_slash_command(app, command_text: str, attachments: list | None = None) -> bool:
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
        if attachments:
            try:
                chat_input = app.query_one("#message-input")
                chat_input.clipboard_attachments = list(attachments)
                chat_input.update_attachment_bar()
            except Exception:
                pass
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
            prompt = f"{skills_content}\n\n{user_request}"
        else:
            prompt = skills_content

        if getattr(app, "is_generating", False) is True and hasattr(app, "_queue_message_ui"):
            app._queue_message_ui(prompt, show_in_ui=True, attachments=attachments, display_text=command_text)
        else:
            kwargs = {"attachments": attachments} if attachments else {}
            app.trigger_ai_response(prompt, show_in_ui=True, display_text=command_text, **kwargs)
        return True

    # MCP prompt execution fallback (e.g. /simple-prompt or /args-prompt topic=Python)
    if words and words[0].startswith("/"):
        raw_mcp_name = words[0][1:]
        clean_mcp_name = "".join(homoglyphs.get(c, c) for c in raw_mcp_name.lower())
        try:
            from core.infrastructure.mcp import get_mcp_manager

            mm = get_mcp_manager()
            args_dict: dict[str, str] = {}
            extra_text = []
            for w in words[1:]:
                if "=" in w:
                    k, v = w.split("=", 1)
                    args_dict[k.strip()] = v.strip()
                else:
                    extra_text.append(w)

            target_server = None
            prompt_lookup_name = clean_mcp_name
            if "__" in clean_mcp_name:
                target_server, prompt_lookup_name = clean_mcp_name.split("__", 1)

            prompt_data = await mm.get_prompt_async(
                prompt_lookup_name, arguments=args_dict, server_name=target_server
            )
            if prompt_data:
                messages = prompt_data.get("messages", [])
                out_parts = []
                for msg in messages:
                    content = msg.get("content")
                    if isinstance(content, dict):
                        if content.get("type") == "text":
                            out_parts.append(content.get("text", ""))
                        else:
                            out_parts.append(str(content))
                    elif isinstance(content, str):
                        out_parts.append(content)
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                out_parts.append(item.get("text", ""))
                            else:
                                out_parts.append(str(item))
                if extra_text:
                    out_parts.append(" ".join(extra_text))
                final_prompt = "\n\n".join(p for p in out_parts if p).strip()
                if final_prompt:
                    if getattr(app, "is_generating", False) is True and hasattr(app, "_queue_message_ui"):
                        app._queue_message_ui(final_prompt, show_in_ui=True, attachments=attachments, display_text=command_text)
                    else:
                        kwargs = {"attachments": attachments} if attachments else {}
                        app.trigger_ai_response(final_prompt, show_in_ui=True, display_text=command_text, **kwargs)
                    return True
        except Exception:
            pass

    return False
