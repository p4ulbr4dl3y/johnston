import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App, ComposeResult

from widgets.chat_input import ChatInput
from widgets.commands import ResumeCommand
from widgets.presentation.screens.resume import ResumeScreen
from widgets.presentation.screens.session_conflict import SessionConflictScreen


class ConflictTestApp(App):
    def compose(self) -> ComposeResult:
        yield from ()


class TestSessionConflictScreen(unittest.IsolatedAsyncioTestCase):
    async def test_session_conflict_screen_options(self):
        app = ConflictTestApp()
        async with app.run_test():
            screen = SessionConflictScreen(session_id="s1")
            self.assertEqual(screen.raw_items, ["readonly", "steal"])
            self.assertEqual(screen.default_value, "readonly")
            self.assertIn("read-only", screen.raw_options[0])
            self.assertIn("Steal", screen.raw_options[1])

    async def test_resume_screen_locked_icon(self):
        sessions = [
            {"id": "s1", "title": "Active Here", "message_count": 2, "is_locked": False},
            {"id": "s2", "title": "Locked Elsewhere", "message_count": 5, "is_locked": True},
            {"id": "s3", "title": "Normal Old Session", "message_count": 1, "is_locked": False},
        ]
        screen = ResumeScreen(sessions, current_session_id="s1")
        opts = screen._format_all_options(78)
        self.assertTrue(opts[0].startswith("● "))
        self.assertTrue(opts[1].startswith("◆ "))
        self.assertTrue(opts[2].startswith("  "))

    async def test_resume_command_opens_conflict_screen_when_locked(self):
        app = MagicMock()
        app.sm = MagicMock()
        app.sm.list_main_sessions.return_value = [
            {"id": "s_locked", "title": "Busy Task", "message_count": 4, "is_locked": True}
        ]
        app.sm.is_session_locked.return_value = True

        cmd = ResumeCommand()
        await cmd.execute(app)

        # ResumeScreen pushed
        app.push_screen.assert_called()
        resume_callback = app.push_screen.call_args[1]["callback"]

        # User selects locked session
        with patch("widgets.presentation.screens.session_conflict.SessionConflictScreen"):
            resume_callback("s_locked")
            # SessionConflictScreen pushed
            app.push_screen.assert_called()
            conflict_cb = app.push_screen.call_args[1]["callback"]

            # 1. Test Steal
            conflict_cb("steal")
            app.sm.steal_session_lock.assert_called_with("s_locked")
            app.load_session_ui.assert_called_with("s_locked")

            # 2. Test ReadOnly
            conflict_cb("readonly")
            app.load_session_ui.assert_called_with("s_locked", read_only=True)

            # 3. Test Cancel / Esc: returns back to ResumeScreen
            conflict_cb(None)
            self.assertIsInstance(app.push_screen.call_args[0][0], ResumeScreen)

    async def test_new_command_resets_read_only_and_manages_locks(self):
        from widgets.commands import NewCommand

        app = MagicMock()
        app.sm = MagicMock()
        app.current_session_id = "old_sess"
        app.is_read_only = True
        app.message_queue = MagicMock()
        chat_view = MagicMock()
        chat_view.remove_children = AsyncMock()
        app.query_one.return_value = chat_view

        with patch("widgets.commands.new_session", return_value="new_sess"):
            cmd = NewCommand()
            await cmd.execute(app)

            app.sm.release_session_lock.assert_called_with("old_sess")
            app.sm.acquire_session_lock.assert_called_with("new_sess")
            self.assertFalse(app.is_read_only)
            self.assertEqual(app.current_session_id, "new_sess")

    async def test_message_flow_auto_forks_when_read_only(self):
        from widgets.mixins.message_flow import MessageFlowMixin

        class TestApp(MessageFlowMixin):
            def __init__(self):
                self.is_generating = False
                self.is_read_only = True
                self.current_session_id = "orig_sess"
                self.sm = MagicMock()
                self.trigger_ai_response = MagicMock()
                self._input = MagicMock()
                self._input.placeholder = ""
                self.query_one = lambda sel, cls=None: self._input

        test_app = TestApp()
        forked_mock = MagicMock(id="orig_sess_fork")
        test_app.sm.fork_session.return_value = forked_mock

        ev = ChatInput.Submitted("hello from readonly")
        await test_app.on_chat_input_submitted(ev)

        test_app.sm.fork_session.assert_called_with("orig_sess")
        self.assertEqual(test_app.current_session_id, "orig_sess_fork")
        test_app.sm.acquire_session_lock.assert_called_with("orig_sess_fork")
        test_app.sm.set_active_session_id.assert_called_with("orig_sess_fork")
        self.assertFalse(test_app.is_read_only)
        test_app.trigger_ai_response.assert_called_with("hello from readonly", show_in_ui=True)
