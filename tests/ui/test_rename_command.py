import unittest
from unittest.mock import MagicMock

from widgets.presentation.commands import RenameCommand


class TestRenameCommand(unittest.IsolatedAsyncioTestCase):
    async def test_rename_command_no_active_session(self):
        app = MagicMock()
        app.current_session_id = None
        cmd = RenameCommand()
        await cmd.execute(app)
        app.notify.assert_called_with("No active session to rename", severity="warning")

    async def test_rename_command_session_not_found(self):
        app = MagicMock()
        app.current_session_id = "non_existent"
        app.sm.get.return_value = None
        app.sm.create_main.side_effect = Exception("failed")
        cmd = RenameCommand()
        await cmd.execute(app)
        app.notify.assert_called_with("Session not found", severity="error")

    async def test_rename_command_creates_session_on_fresh_startup(self):
        app = MagicMock()
        app.current_session_id = "fresh_sess_id"
        app.role = "worker"
        app.sm.get.return_value = None
        fresh_sess = MagicMock()
        fresh_sess.title = ""
        fresh_sess.messages = []
        app.sm.create_main.return_value = fresh_sess

        def push_screen_mock(screen, callback):
            self.assertEqual(screen.current_title, "")
            callback("Startup Session Name")

        app.push_screen = push_screen_mock
        cmd = RenameCommand()
        await cmd.execute(app)

        app.sm.create_main.assert_called_with("fresh_sess_id", role="worker")
        self.assertEqual(fresh_sess.title, "Startup Session Name")
        app.sm.save.assert_called_with(fresh_sess)
        app.notify.assert_called_with("Session renamed", severity="information", timeout=1.5)

    async def test_rename_command_successful_rename(self):
        app = MagicMock()
        app.current_session_id = "sess_1"
        mock_sess = MagicMock()
        mock_sess.title = "Old Title"
        app.sm.get.return_value = mock_sess

        def push_screen_mock(screen, callback):
            callback("Updated Feature Title")

        app.push_screen = push_screen_mock
        cmd = RenameCommand()
        await cmd.execute(app)

        self.assertEqual(mock_sess.title, "Updated Feature Title")
        app.sm.save.assert_called_with(mock_sess)
        app.refresh_status_footer.assert_called()
        app.notify.assert_called_with("Session renamed", severity="information", timeout=1.5)

    async def test_rename_command_empty_welcome_session(self):
        app = MagicMock()
        app.current_session_id = "empty_sess"
        empty_sess = MagicMock()
        empty_sess.title = "Untitled"
        empty_sess.messages = []
        app.sm.get.return_value = empty_sess

        def push_screen_mock(screen, callback):
            self.assertEqual(screen.current_title, "")
            callback("Planned Architecture Refactor")

        app.push_screen = push_screen_mock
        cmd = RenameCommand()
        await cmd.execute(app)

        self.assertEqual(empty_sess.title, "Planned Architecture Refactor")
        app.sm.save.assert_called_with(empty_sess)
        app.notify.assert_called_with("Session renamed", severity="information", timeout=1.5)
