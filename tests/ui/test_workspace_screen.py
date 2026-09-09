"""Tests for widgets/presentation/screens/workspace.py."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from textual.app import App
from textual.events import Paste
from textual.widgets import Input, OptionList

from core.application.permission.permission_manager import PermissionManager
from widgets.presentation.commands.workspace_command import WorkspaceCommand
from widgets.presentation.screens.confirm import ConfirmScreen
from widgets.presentation.screens.workspace import (
    WorkspaceScreen,
    format_workspace_path,
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
        import json
        from unittest.mock import patch

        # Primary
        self.assertEqual(get_root_scope(self.pm, self.project_dir), "primary")

        # Session
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            self.pm.add_workspace_root(extra)
            self.assertEqual(get_root_scope(self.pm, extra), "session")
        finally:
            os.rmdir(extra)

        # Local
        local_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            dot_j = os.path.join(self.project_dir, ".johnston")
            os.makedirs(dot_j, exist_ok=True)
            with open(os.path.join(dot_j, "config.local.json"), "w", encoding="utf-8") as f:
                json.dump({"permissions": {"writable_roots": [local_dir]}}, f)
            self.assertEqual(get_root_scope(self.pm, local_dir), "local")
        finally:
            os.rmdir(local_dir)

        # Project
        proj_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            dot_j = os.path.join(self.project_dir, ".johnston")
            os.makedirs(dot_j, exist_ok=True)
            with open(os.path.join(dot_j, "config.json"), "w", encoding="utf-8") as f:
                json.dump({"permissions": {"writable_roots": [proj_dir]}}, f)
            self.assertEqual(get_root_scope(self.pm, proj_dir), "project")
        finally:
            os.rmdir(proj_dir)

        # Global
        global_dir = os.path.realpath(tempfile.mkdtemp())
        global_cfg = os.path.join(self.temp_dir.name, "fake_global_config.json")
        try:
            with open(global_cfg, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"writable_roots": [global_dir]}}, f)
            with patch("core.application.permission.permission_manager.CONFIG_FILE", global_cfg):
                self.assertEqual(get_root_scope(self.pm, global_dir), "global")
                # Also test remove_persisted_workspace_root on global config
                self.pm.remove_persisted_workspace_root(global_dir)
                with open(global_cfg, "r", encoding="utf-8") as f:
                    after = json.load(f)
                self.assertNotIn(global_dir, after.get("permissions", {}).get("writable_roots", []))
        finally:
            os.rmdir(global_dir)

    def test_format_workspace_path(self):
        home = os.path.realpath(os.path.expanduser("~"))
        # Within home
        test_path = os.path.join(home, "projects", "my-repo")
        self.assertEqual(format_workspace_path(test_path, 50), "~/projects/my-repo")

        # Home itself
        self.assertEqual(format_workspace_path(home, 50), "~")

        # Middle truncation when exceeding max_width
        deep_path = os.path.join(home, "dev", "workspaces", "team", "long-name", "project-x")
        formatted = format_workspace_path(deep_path, 25)
        self.assertIn("/.../project-x", formatted)
        self.assertTrue(len(formatted) <= 25)

        # Path outside home
        outside = "/private/var/custom/deep/sub/new_root"
        formatted_outside = format_workspace_path(outside, 24)
        self.assertIn("/.../new_root", formatted_outside)
        self.assertTrue(len(formatted_outside) <= 24)

        # Empty
        self.assertEqual(format_workspace_path("", 50), "")

    async def test_workspace_screen_render(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            self.pm.add_workspace_root(extra)
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                opt_list = screen.query_one("#workspace-option-list", OptionList)
                # Exactly 2 roots (no divider or add item)
                self.assertEqual(len(opt_list._options), 2)
                self.assertEqual(len(screen.roots_data), 2)
                self.assertEqual(screen.roots_data[0]["scope"], "primary")
                self.assertEqual(screen.roots_data[1]["scope"], "session")

                # Input is present and focused initially, list has no ghost highlight
                inp = screen.query_one("#workspace-add-input", Input)
                self.assertTrue(inp.has_focus)
                self.assertIsNone(opt_list.highlighted)

                # Hint shows input action
                hint = screen.query_one("#modal-hint", ModalHint)
                self.assertIn("enter Add", str(hint.left_text))
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

                # Focus list on primary root (index 0)
                opt_list.focus()
                await pilot.pause()
                opt_list.highlighted = 0
                screen._update_hint(0)
                self.assertNotIn("d Delete", str(hint.left_text))
                self.assertIn("drop folder", str(hint.left_text))

                # Removable root (index 1)
                opt_list.highlighted = 1
                screen._update_hint(1)
                self.assertIn("d Delete", str(hint.left_text))

                # Return focus to input
                inp = screen.query_one("#workspace-add-input", Input)
                inp.focus()
                await pilot.pause()
                screen._update_hint()
                self.assertIn("enter Add", str(hint.left_text))
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_navigation_keys(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            self.pm.add_workspace_root(extra)
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                inp = screen.query_one("#workspace-add-input", Input)
                opt_list = screen.query_one("#workspace-option-list", OptionList)

                self.assertTrue(inp.has_focus)
                # Down from input -> moves focus to OptionList (first item)
                await pilot.press("down")
                await pilot.pause()
                self.assertTrue(opt_list.has_focus)
                self.assertEqual(opt_list.highlighted, 0)

                # Down to last item (index 1)
                await pilot.press("down")
                await pilot.pause()
                self.assertEqual(opt_list.highlighted, 1)

                # Down from last item -> loops back to Input!
                await pilot.press("down")
                await pilot.pause()
                self.assertTrue(inp.has_focus)

                # Up from Input -> moves to last item in OptionList!
                await pilot.press("up")
                await pilot.pause()
                self.assertTrue(opt_list.has_focus)
                self.assertEqual(opt_list.highlighted, 1)

                # Up to first item (index 0)
                await pilot.press("up")
                await pilot.pause()
                self.assertEqual(opt_list.highlighted, 0)

                # Up from top of OptionList -> moves focus back to Input
                await pilot.press("up")
                await pilot.pause()
                self.assertTrue(inp.has_focus)

                # Test _clear_selection on focus
                inp.value = "/some/test/path"
                inp._on_focus(MagicMock())
                self.assertEqual(inp.cursor_position, len(inp.value))
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_cannot_remove_primary(self):
        screen = WorkspaceScreen(pm=self.pm)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#workspace-option-list", OptionList)
            opt_list.focus()
            await pilot.pause()
            opt_list.highlighted = 0
            screen.action_remove_root()
            await pilot.pause()
            self.assertTrue(any("Primary workspace root cannot be removed" in n for n in app.notifications))

    async def test_workspace_screen_select_removable_prompts_confirm(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            self.pm.add_workspace_root(extra)
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                opt_list = screen.query_one("#workspace-option-list", OptionList)
                opt_list.focus()
                # Removable root is at index 1
                opt_list.highlighted = 1
                await pilot.press("enter")
                await pilot.pause()
                self.assertIsInstance(app.screen, ConfirmScreen)
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_input_empty_noop(self):
        screen = WorkspaceScreen(pm=self.pm)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = screen.query_one("#workspace-add-input", Input)
            inp.value = ""
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(len(app.notifications), 0)

    async def test_workspace_screen_input_nonexistent_warns(self):
        screen = WorkspaceScreen(pm=self.pm)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = screen.query_one("#workspace-add-input", Input)
            inp.value = "/nonexistent/random/path/xyz987"
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(any("does not exist" in n for n in app.notifications))

    async def test_workspace_screen_input_adds_session_root(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                inp = screen.query_one("#workspace-add-input", Input)
                inp.value = extra
                await pilot.press("enter")
                await pilot.pause()

                self.assertIn(extra, self.pm.get_workspace_roots())
                self.assertEqual(get_root_scope(self.pm, extra), "session")
                # Input is cleared
                self.assertEqual(inp.value, "")

                # Option list refreshed
                opt_list = screen.query_one("#workspace-option-list", OptionList)
                self.assertEqual(len(opt_list._options), 2)
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_input_paste_decodes(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                screen.on_paste(Paste(f"'{extra}'"))
                await pilot.pause()
                inp = screen.query_one("#workspace-add-input", Input)
                self.assertEqual(inp.value, extra)
        finally:
            os.rmdir(extra)

    async def test_workspace_screen_drag_and_drop(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            screen = WorkspaceScreen(pm=self.pm)
            app = _HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                # When input does NOT have focus (e.g. OptionList has focus)
                opt_list = screen.query_one("#workspace-option-list", OptionList)
                opt_list.focus()
                await pilot.pause()

                # Simulate dropping folder path directly on modal
                screen.on_paste(Paste(f"file://{extra}"))
                await pilot.pause()
                self.assertIn(extra, self.pm.get_workspace_roots())
        finally:
            os.rmdir(extra)

    async def test_workspace_command_pushes_screen_when_available(self):
        mock_app = MagicMock()
        mock_app.push_screen = MagicMock()
        cmd = WorkspaceCommand()
        await cmd.execute(mock_app)
        mock_app.push_screen.assert_called_once()
        called_screen = mock_app.push_screen.call_args[0][0]
        self.assertIsInstance(called_screen, WorkspaceScreen)
