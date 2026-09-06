"""Tests for widgets/presentation/screens/workspace.py."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from textual.app import App
from textual.widgets import Input, OptionList

from core.permission_manager import PermissionManager
from widgets.presentation.commands.workspace_command import WorkspaceCommand
from widgets.presentation.screens.workspace import (
    AddWorkspaceRootScreen,
    WorkspaceScreen,
    get_root_scope,
)


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
                # First is "+ Add workspace root...", followed by primary and extra
                self.assertEqual(len(opt_list._options), 3)
                self.assertEqual(len(screen.roots_data), 2)
                self.assertEqual(screen.roots_data[0]["scope"], "primary")
                self.assertEqual(screen.roots_data[1]["scope"], "session")
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_cannot_remove_primary(self):
        screen = WorkspaceScreen(pm=self.pm)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#workspace-option-list", OptionList)
            # Highlight primary root (index 1)
            opt_list.highlighted = 1
            screen.action_remove_root()
            await pilot.pause()
            self.assertTrue(any("Primary workspace root cannot be removed" in n for n in app.notifications))

    async def test_workspace_screen_select_add_opens_modal(self):
        screen = WorkspaceScreen(pm=self.pm)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#workspace-option-list", OptionList)
            opt_list.highlighted = 0
            # Press enter / select "+ Add..."
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
                opt_list.highlighted = 2
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
