"""Tests for BranchCommand, BranchScreen, and branch switching lifecycle."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App
from textual.widgets import OptionList

from widgets.presentation.commands.branch_command import BranchCommand
from widgets.presentation.screens.branch import (
    BranchInput,
    BranchOptionList,
    BranchScreen,
)
from widgets.presentation.screens.confirm import ConfirmScreen
from widgets.presentation.widgets.modal_hint import ModalHint


class _HostApp(App[None]):
    def __init__(self, screen_to_test: BranchScreen) -> None:
        super().__init__()
        self.screen_to_test = screen_to_test
        self.notifications: list[str] = []
        self.switched_dirs: list[tuple[str, str]] = []
        self.project_dir = "/tmp/fake-repo"

    def on_mount(self) -> None:
        self.push_screen(self.screen_to_test)

    def notify(self, message: str, **kwargs) -> None:
        self.notifications.append(message)

    def switch_project_dir(self, new_dir: str, branch: str = "") -> None:
        self.switched_dirs.append((new_dir, branch))
        self.project_dir = new_dir


class TestBranchCommand(unittest.IsolatedAsyncioTestCase):
    def test_branch_command_metadata(self) -> None:
        cmd = BranchCommand()
        self.assertEqual(cmd.name, "/branch")
        self.assertIn("/b", cmd.aliases)
        self.assertIn("/wt", cmd.aliases)
        self.assertIn("/worktree", cmd.aliases)
        self.assertEqual(cmd.description, "Manage git branches and worktrees")

    async def test_branch_command_pushes_screen(self) -> None:
        mock_app = MagicMock()
        mock_app.push_screen = MagicMock()
        cmd = BranchCommand()
        await cmd.execute(mock_app)
        mock_app.push_screen.assert_called_once()
        screen = mock_app.push_screen.call_args[0][0]
        self.assertIsInstance(screen, BranchScreen)

    async def test_branch_command_cli_fallback(self) -> None:
        class CliApp:
            def __init__(self) -> None:
                self.project_dir = "/tmp/repo"
                self.messages: list[str] = []

            def query_one(self, cls):
                mock_cv = MagicMock()
                mock_bm = MagicMock()

                async def add_bot_message():
                    return mock_bm

                mock_cv.add_bot_message = add_bot_message
                return mock_cv

        app = CliApp()
        mock_mgr = MagicMock()
        mock_mgr.list_branches_and_worktrees_async = AsyncMock(
            return_value=[
                {"branch": "main", "is_root": True, "is_current": True, "path": "/tmp/repo"},
                {"branch": "feat/1", "is_worktree": True, "path": "/tmp/repo-wt-1"},
            ]
        )

        cmd = BranchCommand()
        with patch("core.infrastructure.runtime.git_worktree.GitWorktreeManager", mock_mgr):
            await cmd.execute(app)


class TestBranchScreen(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.mock_mgr = MagicMock()
        self.mock_mgr.list_branches_and_worktrees_async = AsyncMock(
            return_value=[
                {"branch": "main", "is_root": True, "is_current": True, "path": "/tmp/repo"},
                {"branch": "feat/existing-wt", "is_worktree": True, "is_current": False, "path": "/tmp/repo-wt-1"},
                {"branch": "feat/local-only", "is_worktree": False, "is_current": False, "path": ""},
                {"branch": "origin/remote-only", "is_worktree": False, "is_current": False, "is_remote": True, "path": ""},
            ]
        )
        self.mock_mgr.create_worktree_async = AsyncMock(return_value="/tmp/worktrees/repo/feat-new")
        self.mock_mgr.check_merge_conflicts_async = AsyncMock(return_value=False)
        self.mock_mgr.merge_branch_async = AsyncMock(return_value=True)
        self.mock_mgr.remove_worktree_async = AsyncMock(return_value=True)

    async def test_branch_screen_render_and_options(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#branch-option-list", OptionList)
            self.assertEqual(len(opt_list._options), 4)

            # First item is main (repo root, current)
            self.assertEqual(screen._option_actions[0][0], "branch")
            self.assertEqual(screen._option_actions[0][1]["branch"], "main")
            self.assertEqual(screen.current_branch_name, "main")

            # Input has focus initially
            inp = screen.query_one("#branch-input", BranchInput)
            self.assertTrue(inp.has_focus)
            self.assertIsNone(opt_list.highlighted)

            hint = screen.query_one("#modal-hint", ModalHint)
            self.assertIn("enter Switch/Create", str(hint.left_text))
            self.assertEqual(hint.right_text, "4/4")

    async def test_branch_screen_filter_and_new_option(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = screen.query_one("#branch-input", BranchInput)
            opt_list = screen.query_one("#branch-option-list", OptionList)

            # Type filter that matches nothing -> creates top 'new' option
            inp.value = "feat/brand-new"
            await pilot.pause()

            self.assertEqual(len(opt_list._options), 1)
            self.assertEqual(screen._option_actions[0][0], "new")
            self.assertEqual(screen._option_actions[0][1]["branch"], "feat/brand-new")
            hint = screen.query_one("#modal-hint", ModalHint)
            self.assertEqual(hint.right_text, "0/4")

    async def test_branch_screen_switch_existing_worktree(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#branch-option-list", OptionList)
            opt_list.focus()
            # Index 1 is feat/existing-wt
            opt_list.highlighted = 1
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.switched_dirs, [("/tmp/repo-wt-1", "feat/existing-wt")])
            self.assertTrue(any("Switched to worktree" in n for n in app.notifications))

    async def test_branch_screen_switch_repo_root(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#branch-option-list", OptionList)
            opt_list.focus()
            # Index 0 is main repo root
            opt_list.highlighted = 0
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.switched_dirs, [("/tmp/repo", "main")])

    async def test_branch_screen_create_worktree_on_branch(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#branch-option-list", OptionList)
            opt_list.focus()
            # Index 2 is feat/local-only (no worktree yet)
            opt_list.highlighted = 2
            await pilot.press("enter")
            await pilot.pause()

            self.mock_mgr.create_worktree_async.assert_called_once_with("/tmp/repo", "feat/local-only")
            self.assertEqual(app.switched_dirs, [("/tmp/worktrees/repo/feat-new", "feat/local-only")])

    async def test_branch_screen_input_submitted_new(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = screen.query_one("#branch-input", BranchInput)
            inp.value = "feat/auto-create"
            await pilot.press("enter")
            await pilot.pause()

            self.mock_mgr.create_worktree_async.assert_called_with("/tmp/repo", "feat/auto-create")
            self.assertEqual(app.switched_dirs, [("/tmp/worktrees/repo/feat-new", "feat/auto-create")])

    async def test_branch_screen_create_worktree_failure(self) -> None:
        self.mock_mgr.create_worktree_async = AsyncMock(return_value=None)
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = screen.query_one("#branch-input", BranchInput)
            inp.value = "feat/failing"
            await pilot.press("enter")
            await pilot.pause()

            self.assertTrue(any("Failed to create worktree" in n for n in app.notifications))
            self.assertEqual(len(app.switched_dirs), 0)

    async def test_branch_screen_merge_clean(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#branch-option-list", OptionList)
            opt_list.focus()
            # Index 1 is feat/existing-wt
            opt_list.highlighted = 1
            await pilot.press("m")
            await pilot.pause()

            # Clean merge prompts ConfirmScreen
            self.assertIsInstance(app.screen, ConfirmScreen)
            # Confirm
            await pilot.press("enter")
            await pilot.pause()

            self.mock_mgr.merge_branch_async.assert_called_once_with("/tmp/repo", "feat/existing-wt", "main")
            self.assertTrue(any("Successfully merged" in n for n in app.notifications))

    async def test_branch_screen_merge_conflict(self) -> None:
        self.mock_mgr.check_merge_conflicts_async = AsyncMock(return_value=True)
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#branch-option-list", OptionList)
            opt_list.focus()
            opt_list.highlighted = 1
            await pilot.press("m")
            await pilot.pause()

            self.assertNotIsInstance(app.screen, ConfirmScreen)
            self.assertTrue(any("Merge conflict detected" in n for n in app.notifications))

    async def test_branch_screen_merge_self_blocked(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#branch-option-list", OptionList)
            opt_list.focus()
            # Index 0 is main (same as current branch)
            opt_list.highlighted = 0
            await pilot.press("m")
            await pilot.pause()

            self.assertTrue(any("Cannot merge branch into itself" in n for n in app.notifications))

    async def test_branch_screen_delete_worktree(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#branch-option-list", OptionList)
            opt_list.focus()
            # Index 1 is feat/existing-wt (not active, not root)
            opt_list.highlighted = 1
            await pilot.press("d")
            await pilot.pause()

            self.assertIsInstance(app.screen, ConfirmScreen)
            # Confirm deletion
            await pilot.press("enter")
            await pilot.pause()

            self.mock_mgr.remove_worktree_async.assert_called_once_with(
                "/tmp/repo", "/tmp/repo-wt-1", branch_name="feat/existing-wt", delete_branch=False
            )
            self.assertTrue(any("Deleted worktree" in n for n in app.notifications))

    async def test_branch_screen_delete_root_blocked(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#branch-option-list", OptionList)
            opt_list.focus()
            # Index 0 is root
            opt_list.highlighted = 0
            await pilot.press("d")
            await pilot.pause()

            self.assertTrue(any("Cannot delete repository root" in n for n in app.notifications))

    async def test_branch_screen_delete_active_blocked(self) -> None:
        # Make feat/existing-wt the currently active directory
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        app.project_dir = "/tmp/repo-wt-1"
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#branch-option-list", OptionList)
            opt_list.focus()
            opt_list.highlighted = 1
            await pilot.press("d")
            await pilot.pause()

            self.assertTrue(any("Cannot delete currently active worktree" in n for n in app.notifications))

    async def test_branch_screen_keyboard_navigation(self) -> None:
        screen = BranchScreen(project_dir="/tmp/repo", manager=self.mock_mgr)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = screen.query_one("#branch-input", BranchInput)
            opt_list = screen.query_one("#branch-option-list", BranchOptionList)

            self.assertTrue(inp.has_focus)
            # Down from input focuses option list
            await pilot.press("down")
            await pilot.pause()
            self.assertTrue(opt_list.has_focus)
            self.assertEqual(opt_list.highlighted, 0)

            # Move to last item
            opt_list.highlighted = len(opt_list._options) - 1
            # Down from last loops back to input
            await pilot.press("down")
            await pilot.pause()
            self.assertTrue(inp.has_focus)

            # Up from input goes to last item
            await pilot.press("up")
            await pilot.pause()
            self.assertTrue(opt_list.has_focus)
            self.assertEqual(opt_list.highlighted, len(opt_list._options) - 1)


class TestLifecycleAndStatusState(unittest.TestCase):
    def test_switch_project_dir(self) -> None:
        from core.permission_manager import PermissionManager
        from widgets.mixins.lifecycle import LifecycleMixin

        class DummyApp(LifecycleMixin):
            def __init__(self) -> None:
                self.project_dir = ""
                self.refreshed = False
                self.agent = MagicMock()

            def refresh_status_footer(self) -> None:
                self.refreshed = True

        app = DummyApp()
        orig_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as td:
                real_td = os.path.realpath(td)
                app.switch_project_dir(real_td, branch="feat/test-branch")

                self.assertEqual(app.project_dir, real_td)
                self.assertEqual(app.agent.project_dir, real_td)
                self.assertEqual(app.agent.worktree_branch, "feat/test-branch")
                self.assertTrue(app.refreshed)
                self.assertEqual(PermissionManager.get_instance().current_project_dir, real_td)
        finally:
            os.chdir(orig_cwd)

    def test_build_status_kwargs_uses_app_project_dir(self) -> None:
        from widgets.app.status_state import build_status_kwargs

        mock_app = MagicMock()
        mock_app.project_dir = "/custom/project/dir"
        mock_app.pm = None
        mock_app.agent = None

        kwargs = build_status_kwargs(mock_app)
        self.assertEqual(kwargs["directory"], "/custom/project/dir")
