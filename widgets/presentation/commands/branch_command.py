"""Slash command for managing git branches and worktrees."""
from __future__ import annotations

import os
from typing import Any

from widgets.presentation.commands.base import BaseCommand
from widgets.presentation.widgets.chat_container import ChatView


class BranchCommand(BaseCommand):
    """Open the git branch and worktree management screen."""

    name = "/branch"
    aliases = ["/b", "/wt", "/worktree"]
    description = "Manage git branches and worktrees"

    async def execute(self, app: Any) -> None:
        if hasattr(app, "push_screen"):
            from widgets.presentation.screens.branch import BranchScreen

            app.push_screen(BranchScreen())
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
        pdir = getattr(app, "project_dir", None) or os.getcwd()
        try:
            import asyncio

            from core.infrastructure.runtime.git_worktree import GitWorktreeManager

            if hasattr(GitWorktreeManager, "list_branches_and_worktrees_async"):
                res = GitWorktreeManager.list_branches_and_worktrees_async(pdir)
                branches = await res if asyncio.iscoroutine(res) else res
            elif hasattr(GitWorktreeManager, "list_branches_and_worktrees"):
                branches = await asyncio.to_thread(GitWorktreeManager.list_branches_and_worktrees, pdir)
            else:
                branches = []
        except Exception:
            branches = []

        lines = ["**Git Branches & Worktrees:**"]
        if branches:
            for b in branches:
                name = (
                    b.get("branch") or b.get("name")
                    if isinstance(b, dict)
                    else getattr(b, "branch", getattr(b, "name", str(b)))
                )
                is_curr = (
                    b.get("is_current") or b.get("is_active")
                    if isinstance(b, dict)
                    else getattr(b, "is_current", getattr(b, "is_active", False))
                )
                is_root = b.get("is_root") if isinstance(b, dict) else getattr(b, "is_root", False)
                is_wt = b.get("is_worktree") if isinstance(b, dict) else getattr(b, "is_worktree", False)
                path = (
                    b.get("path") or b.get("worktree_path")
                    if isinstance(b, dict)
                    else getattr(b, "path", getattr(b, "worktree_path", ""))
                )
                badge = "repo root" if is_root else ("worktree" if is_wt else "local")
                tag = " (active)" if is_curr else ""
                path_info = f" -> `{path}`" if path else ""
                lines.append(f"- `{name}` [{badge}]{tag}{path_info}")
        else:
            lines.append("- (no git branches found)")

        await self._post_message(app, "\n".join(lines))
