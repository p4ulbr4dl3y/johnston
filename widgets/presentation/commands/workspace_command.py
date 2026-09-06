"""Slash command for managing allowed workspace roots."""
from __future__ import annotations

import os
import shlex
from typing import Any, Sequence

from core.permission_manager import PermissionManager
from widgets.presentation.commands.base import BaseCommand
from widgets.presentation.widgets.chat_container import ChatView


class WorkspaceCommand(BaseCommand):
    """Command to view, add, or remove allowed workspace roots."""

    name = "/workspace"
    aliases = ["/ws"]
    description = "Manage allowed workspace roots"

    def __init__(self) -> None:
        self.args: list[str] = []

    def set_args(self, args: Sequence[str]) -> None:
        self.args = list(args)

    async def execute(self, app: Any, args: Sequence[str] | str | None = None) -> None:
        raw_args: list[str]
        if args is None:
            raw_args = list(self.args)
        elif isinstance(args, str):
            raw_args = shlex.split(args)
        else:
            raw_args = list(args)

        if raw_args and raw_args[0] in ("/workspace", "/ws"):
            raw_args = raw_args[1:]

        subcmd = raw_args[0].lower() if raw_args else "list"

        if subcmd in ("list", ""):
            await self._handle_list(app)
        elif subcmd == "add":
            await self._handle_add(app, raw_args[1:])
        elif subcmd in ("remove", "rm", "del", "delete"):
            await self._handle_remove(app, raw_args[1:])
        else:
            await self._handle_usage(app)

    async def _post_message(self, app: Any, content: str) -> None:
        try:
            chat_view = app.query_one(ChatView)
            bm = await chat_view.add_bot_message()
            bm.content = content
        except Exception:
            if hasattr(app, "notify"):
                try:
                    app.notify(content)
                except Exception:
                    pass

    async def _handle_list(self, app: Any) -> None:
        pm = PermissionManager.get_instance()
        primary = os.path.realpath(os.getcwd())
        all_roots = pm.get_workspace_roots()

        additional = [r for r in all_roots if os.path.realpath(r) != primary]
        lines = [
            "**Workspace Roots:**",
            f"- **Primary:** `{primary}`",
        ]
        if additional:
            lines.append("- **Additional roots:**")
            for r in additional:
                lines.append(f"  - `{r}`")
        else:
            lines.append("- **Additional roots:** (none)")

        await self._post_message(app, "\n".join(lines))

    async def _handle_add(self, app: Any, args: list[str]) -> None:
        if not args:
            await self._post_message(
                app,
                "Error: Path required. Usage: `/workspace add <path> [--local | --project | --session]`",
            )
            return

        scope = "auto"
        path_tokens = []
        for token in args:
            if token == "--local":
                scope = "local"
            elif token == "--project":
                scope = "project"
            elif token == "--session":
                scope = "session"
            else:
                path_tokens.append(token)

        if not path_tokens:
            await self._post_message(
                app,
                "Error: Path required. Usage: `/workspace add <path> [--local | --project | --session]`",
            )
            return

        raw_path = " ".join(path_tokens)
        abs_path = os.path.abspath(os.path.expanduser(raw_path))
        if not os.path.isdir(abs_path):
            await self._post_message(app, f"Error: Directory '{raw_path}' does not exist.")
            return

        pm = PermissionManager.get_instance()
        used_scope = pm.save_workspace_root(abs_path, scope=scope)
        scope_desc = {
            "session": "session only",
            "local": "local config",
            "project": "project config",
        }.get(used_scope, used_scope)

        await self._post_message(app, f"Added `{abs_path}` to workspace roots ({scope_desc}).")

    async def _handle_remove(self, app: Any, args: list[str]) -> None:
        if not args:
            await self._post_message(app, "Error: Path required. Usage: `/workspace remove <path>`")
            return

        raw_path = " ".join(args)
        abs_path = os.path.abspath(os.path.expanduser(raw_path))

        pm = PermissionManager.get_instance()
        pm.remove_persisted_workspace_root(abs_path)

        await self._post_message(app, f"Removed `{abs_path}` from workspace roots.")

    async def _handle_usage(self, app: Any) -> None:
        msg = (
            "**Workspace Command Usage:**\n"
            "- `/workspace` or `/workspace list`: List current workspace roots\n"
            "- `/workspace add <path> [--local | --project | --session]`: Add allowed workspace root\n"
            "- `/workspace remove <path>`: Remove workspace root"
        )
        await self._post_message(app, msg)
