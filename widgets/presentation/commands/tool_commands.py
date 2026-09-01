"""Tools and subagents slash commands (skills, mcp, subagents, shell tasks, questions, sandbox)."""
from __future__ import annotations

import asyncio

from core.application.skills.manager import get_skill_manager
from core.infrastructure.mcp import get_mcp_manager
from widgets.chat_input import ChatInput
from widgets.presentation.commands.base import BaseCommand
from widgets.presentation.screens.constants import MESSAGE_INPUT
from widgets.presentation.screens.mcp import MCPScreen
from widgets.presentation.screens.skills import SkillsScreen
from widgets.presentation.screens.tasks import ShellTasksScreen, SubagentsScreen


class SkillsCommand(BaseCommand):
    name = "/skills"
    aliases = ["/skill"]
    description = "Browse and activate available skills"

    async def execute(self, app) -> None:
        skills = await asyncio.to_thread(get_skill_manager().list_skills)
        if not skills:
            app.notify("No available skills found", severity="warning")
            return

        def on_skill_selected(selected_skill: dict | None) -> None:
            chat_input = app.query_one(MESSAGE_INPUT, ChatInput)
            if selected_skill:
                s_name = selected_skill["name"]
                chat_input.load_text(f"/{s_name} ")
                lines = chat_input.text.split("\n")
                chat_input.move_cursor((len(lines) - 1, len(lines[-1])))
            chat_input.focus()

        app.push_screen(SkillsScreen(), callback=on_skill_selected)


class MCPCommand(BaseCommand):
    name = "/mcp"
    aliases = ["/mcps"]
    description = "Manage MCP servers"

    async def execute(self, app) -> None:
        mm = get_mcp_manager()
        try:
            servers = await asyncio.to_thread(mm.load_servers)
        except Exception:
            servers = []
        if not servers:
            app.notify("No configured MCP servers found", severity="warning")
            return
        app.push_screen(MCPScreen())


class SubagentsCommand(BaseCommand):
    name = "/subagents"
    aliases = ["/agents", "/subagent"]
    description = "Manage subagents"

    async def execute(self, app) -> None:
        # P1-9: an empty list opens the screen with an empty state instead of a
        # toast — the screen then also explains how to get a subagent going.
        app.push_screen(SubagentsScreen())


class ShellTasksCommand(BaseCommand):
    name = "/shell"
    aliases = ["/tasks", "/shelltasks", "/ps"]
    description = "Manage background shell tasks"

    async def execute(self, app) -> None:
        # See SubagentsCommand: the screen carries its own empty state (P1-9).
        app.push_screen(ShellTasksScreen())


class QuestionsCommand(BaseCommand):
    name = "/questions"
    aliases = ["/q", "/ask"]
    description = "Resume pending user questions"

    async def execute(self, app) -> None:
        from widgets.presentation.screens.ask_user import AskUserWizardScreen

        if hasattr(app, "screen") and isinstance(app.screen, AskUserWizardScreen):
            return

        pending_func = getattr(app, "_pending_ask_user", None)
        if callable(pending_func):
            pending_func()
        else:
            if hasattr(app, "notify"):
                app.notify("No pending questions", severity="warning")


class SandboxCommand(BaseCommand):
    name = "/sandbox"
    aliases = ["/sb"]
    description = "Toggle shell command sandbox"

    async def execute(self, app) -> None:
        if not hasattr(app, "sandbox_enabled"):
            app.sandbox_enabled = False
        app.sandbox_enabled = not app.sandbox_enabled

        from core.infrastructure.config.config_helpers import save_sandbox_config

        try:
            save_sandbox_config(app.sandbox_enabled)
        except Exception:
            pass

        if hasattr(app, "refresh_status_footer"):
            app.refresh_status_footer()
