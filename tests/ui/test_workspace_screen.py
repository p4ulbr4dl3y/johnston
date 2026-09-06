"""Tests for widgets/presentation/screens/workspace.py."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from textual.app import App
from textual.widgets import Input, OptionList, Static

from core.permission_manager import PermissionManager
from widgets.presentation.commands.workspace_command import WorkspaceCommand
from widgets.presentation.screens.workspace import (
    AddWorkspaceRootScreen,
    WorkspaceDirectoryTree,
    WorkspaceScreen,
    get_root_scope,
)
from widgets.presentation.widgets.modal_hint import ModalHint


class _HostApp(App[None]):
    def __init__(self, screen_to_test):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.notifications: list[str] = []

    def on_mount(self) -> None:
        self.push_screen(self.screen_to_test)

    def notify(self, message: str, **kwargs) -> None:
        self.notifications.append(message)


class TestWorkspaceScreen(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = os.path.realpath(self.temp_dir.name)
        os.chdir(self.project_dir)
        self.pm = PermissionManager.configure_instance()
        self.pm.set_project_dir(self.project_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.temp_dir.cleanup()
        self.pm.clear_session_overrides()

    def test_get_root_scope(self):
        # Primary
        self.assertEqual(get_root_scope(self.pm, self.project_dir), "primary")

        # Session
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            self.pm.add_workspace_root(extra)
            self.assertEqual(get_root_scope(self.pm, extra), "session")
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_render(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            self.pm.add_workspace_root(extra)
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                opt_list = screen.query_one("#workspace-option-list", OptionList)
                # 2 roots + 1 divider + 1 "+ Add..." = 4 options
                self.assertEqual(len(opt_list._options), 4)
                self.assertEqual(len(screen.roots_data), 2)
                self.assertEqual(screen.roots_data[0]["scope"], "primary")
                self.assertEqual(screen.roots_data[1]["scope"], "session")

                # Dynamic hint on primary root
                hint = screen.query_one("#modal-hint", ModalHint)
                self.assertIn("a Add", str(hint.left_text))
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_dynamic_hint(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            self.pm.add_workspace_root(extra)
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                opt_list = screen.query_one("#workspace-option-list", OptionList)
                hint = screen.query_one("#modal-hint", ModalHint)

                # Primary root (index 0)
                opt_list.highlighted = 0
                screen._update_hint(0)
                self.assertIn("a Add", str(hint.left_text))
                self.assertNotIn("Delete", str(hint.left_text))

                # Removable root (index 1)
                opt_list.highlighted = 1
                screen._update_hint(1)
                self.assertIn("d Delete", str(hint.left_text))

                # Add option (index 3)
                opt_list.highlighted = 3
                screen._update_hint(3)
                self.assertIn("enter Add", str(hint.left_text))
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_cannot_remove_primary(self):
        screen = WorkspaceScreen(pm=self.pm)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#workspace-option-list", OptionList)
            # Primary root is at index 0
            opt_list.highlighted = 0
            screen.action_remove_root()
            await pilot.pause()
            self.assertTrue(any("Primary workspace root cannot be removed" in n for n in app.notifications))

    async def test_workspace_screen_select_add_opens_modal(self):
        screen = WorkspaceScreen(pm=self.pm)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#workspace-option-list", OptionList)
            # Highlight "+ Add workspace root..." (last item)
            opt_list.highlighted = len(opt_list._options) - 1
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, AddWorkspaceRootScreen)

    async def test_workspace_screen_select_removable_prompts_confirm(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            self.pm.add_workspace_root(extra)
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                opt_list = screen.query_one("#workspace-option-list", OptionList)
                # Removable root is at index 1
                opt_list.highlighted = 1
                await pilot.press("enter")
                await pilot.pause()
                from widgets.presentation.screens.confirm import ConfirmScreen
                self.assertIsInstance(app.screen, ConfirmScreen)
        finally:
            os.rmdir(extra)

    async def test_add_workspace_root_screen_empty(self):
        screen = AddWorkspaceRootScreen()
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = screen.query_one("#workspace-add-input", Input)
            inp.value = ""
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(any("Directory path required" in n for n in app.notifications))

    async def test_add_workspace_root_screen_nonexistent(self):
        screen = AddWorkspaceRootScreen()
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = screen.query_one("#workspace-add-input", Input)
            inp.value = "/nonexistent/random/path/xyz987"
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(any("does not exist" in n for n in app.notifications))

    async def test_add_workspace_root_screen_valid(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            screen = AddWorkspaceRootScreen()
            dismiss_results = []
            screen.dismiss = lambda res=None: dismiss_results.append(res)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                inp = screen.query_one("#workspace-add-input", Input)
                inp.value = f"{extra} --project"
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(len(dismiss_results), 1)
                self.assertEqual(dismiss_results[0], (extra, "project"))
        finally:
            os.rmdir(extra)

    async def test_workspace_command_pushes_screen_when_available(self):
        mock_app = MagicMock()
        mock_app.push_screen = MagicMock()
        cmd = WorkspaceCommand()
        await cmd.execute(mock_app, [])
        mock_app.push_screen.assert_called_once()
        called_screen = mock_app.push_screen.call_args[0][0]
        self.assertIsInstance(called_screen, WorkspaceScreen)

    async def test_workspace_screen_drag_and_drop(self):
        from textual.events import Paste

        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                # Simulate dropping folder path (drag-and-drop from file manager)
                screen.on_paste(Paste(f"file://{extra}"))
                await pilot.pause()
                self.assertIn(extra, self.pm.get_workspace_roots())
                self.assertTrue(any(f"Added `{extra}`" in n for n in app.notifications))
        finally:
            os.rmdir(extra)

    async def test_add_workspace_root_screen_on_paste(self):
        from textual.events import Paste

        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            screen = AddWorkspaceRootScreen()
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                screen.on_paste(Paste(f"'{extra}'"))
                await pilot.pause()
                inp = screen.query_one("#workspace-add-input", Input)
                self.assertEqual(inp.value, extra)
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_split_layout_elements(self):
        screen = WorkspaceScreen(pm=self.pm)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = screen.query_one("#workspace-dir-tree", WorkspaceDirectoryTree)
            header = screen.query_one("#workspace-tree-header", Static)
            info = screen.query_one("#workspace-info-view", Static)
            self.assertIsNotNone(tree)
            self.assertIsNotNone(header)
            self.assertFalse(tree.has_class("-hidden"))
            self.assertTrue(info.has_class("-hidden"))
            self.assertIn(os.path.basename(self.project_dir), str(header.content))

    async def test_workspace_screen_tree_updates_on_highlight(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            self.pm.add_workspace_root(extra)
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                opt_list = screen.query_one("#workspace-option-list", OptionList)
                tree = screen.query_one("#workspace-dir-tree", WorkspaceDirectoryTree)
                info = screen.query_one("#workspace-info-view", Static)

                # Highlight second root (index 1)
                opt_list.highlighted = 1
                screen._update_tree_for_option(1)
                self.assertEqual(os.path.realpath(str(tree.path)), extra)
                self.assertFalse(tree.has_class("-hidden"))

                # Highlight "+ Add workspace root..." (index 3)
                opt_list.highlighted = 3
                screen._update_tree_for_option(3)
                self.assertTrue(tree.has_class("-hidden"))
                self.assertFalse(info.has_class("-hidden"))
                self.assertIn("Extend Johnston's access", str(info.content))
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_toggle_pane(self):
        screen = WorkspaceScreen(pm=self.pm)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#workspace-option-list", OptionList)
            tree = screen.query_one("#workspace-dir-tree", WorkspaceDirectoryTree)

            self.assertTrue(opt_list.has_focus)
            # Press tab to switch to tree
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(tree.has_focus)

            # Press tab again to switch back
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(opt_list.has_focus)

            # Press right arrow from opt_list to focus tree
            await pilot.press("right")
            await pilot.pause()
            self.assertTrue(tree.has_focus)

    def test_workspace_directory_tree_filter(self):
        from pathlib import Path
        tree = WorkspaceDirectoryTree(self.project_dir)
        paths = [
            Path(self.project_dir) / ".git",
            Path(self.project_dir) / ".venv",
            Path(self.project_dir) / "__pycache__",
            Path(self.project_dir) / "node_modules",
            Path(self.project_dir) / "src",
            Path(self.project_dir) / "main.py",
        ]
        filtered = [p.name for p in tree.filter_paths(paths)]
        self.assertEqual(filtered, ["src", "main.py"])

