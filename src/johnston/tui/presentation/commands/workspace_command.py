"""Slash command for managing allowed workspace roots."""
from __future__ import annotations

import os
from typing import Any

from johnston.core.application.permission.permission_manager import PermissionManager
from johnston.tui.presentation.commands.base import BaseCommand
from johnston.tui.presentation.widgets.chat_container import ChatView


class WorkspaceCommand(BaseCommand):
    """Open the workspace roots management screen."""

    name = "/workspace"
    aliases = ["/ws"]
    description = "Manage allowed workspace roots"

    async def execute(self, app: Any) -> None:
        if hasattr(app, "push_screen"):
            from johnston.tui.presentation.screens.workspace import WorkspaceScreen

            app.push_screen(WorkspaceScreen())
            return

        await self._handle_list(app)

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
