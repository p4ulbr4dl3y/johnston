import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from textual.app import App

from core.application.permission.permission_manager import PermissionManager
from widgets.app.dispatch import handle_slash_command
from widgets.presentation.commands.workspace_command import WorkspaceCommand
from widgets.presentation.screens.permission_confirm import PermissionConfirmScreen
from widgets.presentation.widgets.chat_container import ChatView


class HostApp(App[None]):
    def __init__(self, screen):
        super().__init__()
        self.scr = screen

    def on_mount(self):
        self.push_screen(self.scr)


class MockChatView:
    def __init__(self):
        self.messages = []

    async def add_bot_message(self):
        msg = MagicMock()
        msg.content = ""
        self.messages.append(msg)
        return msg


class MockApp:
    def __init__(self):
        self.chat_view = MockChatView()
        self.notifications = []

    def query_one(self, target_cls, *args, **kwargs):
        if target_cls is ChatView:
            return self.chat_view
        raise KeyError(target_cls)

    def notify(self, message, **kwargs):
        self.notifications.append(message)


class TestWorkspaceCommand(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = os.path.realpath(self.temp_dir.name)
        os.chdir(self.project_dir)
        self.pm = PermissionManager.configure_instance()
        self.pm.set_project_dir(self.project_dir)
        self.app = MockApp()

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.temp_dir.cleanup()
        self.pm.clear_session_overrides()

    async def test_workspace_list_empty(self):
        cmd = WorkspaceCommand()
        await cmd.execute(self.app)
        self.assertEqual(len(self.app.chat_view.messages), 1)
        content = self.app.chat_view.messages[0].content
        self.assertIn("Workspace Roots:", content)
        self.assertIn(self.project_dir, content)
        self.assertIn("(none)", content)

    async def test_workspace_list_with_roots(self):
        extra = os.path.realpath(tempfile.mkdtemp())
        try:
            self.pm.add_workspace_root(extra)
            cmd = WorkspaceCommand()
            await cmd.execute(self.app)
            content = self.app.chat_view.messages[0].content
            self.assertIn(extra, content)
        finally:
            os.rmdir(extra)

    async def test_handle_slash_command_dispatch(self):
        handled = await handle_slash_command(self.app, "/workspace")
        self.assertTrue(handled)
        self.assertIn("Workspace Roots:", self.app.chat_view.messages[0].content)

        handled_ws = await handle_slash_command(self.app, "/ws")
        self.assertTrue(handled_ws)


class TestPermissionConfirmScreenWorkspaceIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pm = PermissionManager.configure_instance()

    async def test_permission_confirm_screen_outside_workspace_option(self):
        outside_path = "/var/custom/some/deep/file.py"
        screen = PermissionConfirmScreen("create", {"path": outside_path})
        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()
            self.assertTrue(any(k.startswith("add_root:") for k in screen._option_keys))
            self.assertIn("add_root:/var/custom/some/deep", screen._option_keys)

    async def test_permission_confirm_screen_inside_workspace_no_add_root(self):
        cwd = os.getcwd()
        inside_path = os.path.join(cwd, "test.py")
        screen = PermissionConfirmScreen("create", {"path": inside_path})
        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()
            self.assertFalse(any(k.startswith("add_root:") for k in screen._option_keys))

    async def test_confirm_permission_add_root_action(self):
        from widgets.mixins.actions import ActionsMixin

        class AppWithActions(ActionsMixin):
            def __init__(self, pm=None):
                self.screen = MagicMock()
                self.pm = pm

            def push_screen(self, scr, callback=None):
                if callback:
                    callback("add_root:/var/custom/new_root")

        app = AppWithActions(pm=self.pm)
        res = await app.confirm_permission("create", {"path": "/var/custom/new_root/file.py"}, "testing")
        self.assertTrue(res)
        roots = self.pm.get_workspace_roots()
        self.assertIn(os.path.realpath("/var/custom/new_root"), roots)

    async def test_confirm_permission_save_tool_project(self):
        from widgets.mixins.actions import ActionsMixin

        class AppWithActions(ActionsMixin):
            def __init__(self, pm=None):
                self.screen = MagicMock()
                self.pm = pm

            def push_screen(self, scr, callback=None):
                if callback:
                    callback("always_allow:project")

        app = AppWithActions(pm=self.pm)
        with patch.object(self.pm, "save_tool_permission") as mock_save:
            res = await app.confirm_permission("shell", {"command": "ls"}, "testing", perm_name="shell")
            self.assertTrue(res)
            mock_save.assert_called_once_with("shell", "allow", scope="auto")

    async def test_confirm_permission_save_pattern_project(self):
        from widgets.mixins.actions import ActionsMixin

        class AppWithActions(ActionsMixin):
            def __init__(self, pm=None):
                self.screen = MagicMock()
                self.pm = pm

            def push_screen(self, scr, callback=None):
                if callback:
                    callback("pattern:npm test *:project")

        app = AppWithActions(pm=self.pm)
        with patch.object(self.pm, "save_pattern_permission") as mock_save:
            res = await app.confirm_permission("shell", {"command": "npm test"}, "testing", perm_name="shell")
            self.assertTrue(res)
            mock_save.assert_called_once_with("shell", "npm test *", "allow", scope="auto")
