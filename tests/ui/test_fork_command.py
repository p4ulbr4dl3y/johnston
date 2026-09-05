import unittest
from unittest.mock import MagicMock

from widgets.presentation.commands import ForkCommand


class TestForkCommand(unittest.IsolatedAsyncioTestCase):
    async def _apply_selection(self, app, child_idx):
        """Invoke the pushed screen's callback, awaiting the async handler."""
        import inspect

        cb = app.push_screen.call_args[1]["callback"]
        res = cb(child_idx)
        if inspect.isawaitable(res):
            await res

    async def test_fork_command_empty_history(self):
        app = MagicMock()
        chat_view = MagicMock()
        chat_view.get_user_messages.return_value = []
        app.query_one.return_value = chat_view

        cmd = ForkCommand()
        await cmd.execute(app)
        app.notify.assert_called_with("History is empty: no messages to fork", severity="warning")

    async def test_fork_command_successful_fork_turn_zero(self):
        app = MagicMock()
        chat_view = MagicMock()
        chat_view.get_user_messages.return_value = [(10, "prompt 0"), (20, "prompt 1")]
        app.query_one.return_value = chat_view
        app.current_session_id = "orig_sid"

        parent_sess = MagicMock()
        parent_sess.title = "Parent Title"
        app.sm.get.return_value = parent_sess

        chat_input = MagicMock()
        chat_input.text = "prompt 0"

        def query_one_mock(target, *args, **kwargs):
            if target == "#message-input" or "ChatInput" in str(args):
                return chat_input
            return chat_view

        app.query_one = query_one_mock

        cmd = ForkCommand()
        await cmd.execute(app)

        await self._apply_selection(app, 10)

        app.sm.fork_session.assert_not_called()
        self.assertEqual(
            app.pending_fork,
            {"parent_session_id": "orig_sid", "up_to_msg_index": 0, "title": "prompt 0"},
        )
        chat_view.reset_to_messages.assert_called_with([], task_manager=unittest.mock.ANY)
        chat_input.load_text.assert_called_with("prompt 0")
        chat_input.focus.assert_called()

    async def test_fork_command_successful_fork_turn_subsequent(self):
        app = MagicMock()
        chat_view = MagicMock()
        chat_view.get_user_messages.return_value = [(10, "prompt 0"), (20, "second turn prompt")]
        app.query_one.return_value = chat_view
        app.current_session_id = "orig_sid"

        chat_input = MagicMock()
        chat_input.text = "second turn prompt"

        def query_one_mock(target, *args, **kwargs):
            if target == "#message-input" or "ChatInput" in str(args):
                return chat_input
            return chat_view

        app.query_one = query_one_mock

        cmd = ForkCommand()
        await cmd.execute(app)
        await self._apply_selection(app, 20)

        app.sm.fork_session.assert_not_called()
        self.assertEqual(
            app.pending_fork,
            {"parent_session_id": "orig_sid", "up_to_msg_index": 1, "title": "second turn prompt"},
        )
        chat_view.reset_to_messages.assert_called()
        chat_input.load_text.assert_called_with("second turn prompt")

    async def test_fork_command_truncates_long_branch_title(self):
        from core.domain.policies.session_naming import FORK_BASE_MAX_LEN

        app = MagicMock()
        chat_view = MagicMock()
        long_prompt = "rewrite the parser " * 10
        chat_view.get_user_messages.return_value = [(10, "prompt 0"), (20, long_prompt)]
        app.query_one.return_value = chat_view
        app.current_session_id = "orig_sid"

        chat_input = MagicMock()
        chat_input.text = long_prompt

        def query_one_mock(target, *args, **kwargs):
            if target == "#message-input" or "ChatInput" in str(args):
                return chat_input
            return chat_view

        app.query_one = query_one_mock

        cmd = ForkCommand()
        await cmd.execute(app)
        await self._apply_selection(app, 20)

        base = app.pending_fork["title"]
        self.assertLessEqual(len(base), FORK_BASE_MAX_LEN)
        self.assertNotIn("(fork", base)

    async def test_fork_command_successful_fork_current_state(self):
        from widgets.presentation.screens.fork import FORK_CURRENT_STATE

        app = MagicMock()
        chat_view = MagicMock()
        chat_view.get_user_messages.return_value = [(10, "prompt 0"), (20, "second turn prompt")]
        app.query_one.return_value = chat_view
        app.current_session_id = "orig_sid"

        parent_sess = MagicMock()
        parent_sess.title = "My Session"
        app.sm.get.return_value = parent_sess

        chat_input = MagicMock()
        chat_input.text = ""

        def query_one_mock(target, *args, **kwargs):
            if target == "#message-input" or "ChatInput" in str(args):
                return chat_input
            return chat_view

        app.query_one = query_one_mock

        cmd = ForkCommand()
        await cmd.execute(app)
        await self._apply_selection(app, FORK_CURRENT_STATE)

        app.sm.fork_session.assert_not_called()
        self.assertEqual(
            app.pending_fork,
            {"parent_session_id": "orig_sid", "up_to_msg_index": None, "title": None},
        )
        chat_input.load_text.assert_called_with("")
        chat_input.focus.assert_called()

    async def test_pending_fork_applied_on_message_submit(self):
        from widgets.chat_input import ChatInput
        from widgets.mixins.message_flow import MessageFlowMixin

        class TestApp(MessageFlowMixin):
            def __init__(self):
                self.is_generating = False
                self.is_read_only = False
                self.current_session_id = "orig_sid"
                self.pending_fork = {
                    "parent_session_id": "orig_sid",
                    "up_to_msg_index": 0,
                    "title": "Parent Title",
                }
                self.sm = MagicMock()
                self.trigger_ai_response = MagicMock()
                self.notify = MagicMock()
                self.refresh_status_footer = MagicMock()
                self._input = MagicMock()
                self._input.placeholder = ""
                self.query_one = lambda sel, cls=None: self._input

        test_app = TestApp()
        forked_mock = MagicMock(id="forked_sid")
        test_app.sm.fork_session.return_value = forked_mock

        ev = ChatInput.Submitted("new prompt in forked session")
        await test_app.on_chat_input_submitted(ev)

        test_app.sm.fork_session.assert_called_with(
            "orig_sid", new_title="Parent Title", up_to_msg_index=0
        )
        self.assertEqual(test_app.current_session_id, "forked_sid")
        self.assertIsNone(test_app.pending_fork)
        test_app.sm.acquire_session_lock.assert_called_with("forked_sid")
        test_app.sm.set_active_session_id.assert_called_with("forked_sid")
        test_app.notify.assert_called_with("Session forked", severity="information", timeout=1.5)
        test_app.trigger_ai_response.assert_called_with("new prompt in forked session", show_in_ui=True)

    async def test_fork_then_rewind_cancels_pending_fork_and_executes_rewind(self):
        import inspect

        from widgets.presentation.commands import RewindCommand
        from widgets.presentation.screens.rewind import RewindSelection

        app = MagicMock()
        chat_view = MagicMock()
        chat_view.PAGE_SIZE = 50
        chat_view.get_user_messages.return_value = [(10, "prompt 0"), (20, "prompt 1")]
        chat_input = MagicMock()
        chat_input.text = "prompt 0"
        plan_notch = MagicMock()
        def q_mock(target, *args, **kwargs):
            if "PlanNotch" in str(target):
                return plan_notch
            if "#message-input" in str(target):
                return chat_input
            return chat_view
        app.query_one.side_effect = q_mock
        app.current_session_id = "orig_sid"
        app.save_current_session_async = unittest.mock.AsyncMock()
        app.pending_fork = {"parent_session_id": "orig_sid", "up_to_msg_index": 1, "title": "fork"}

        session_mock = MagicMock()
        session_mock.messages = [
            {"type": "user", "text": "prompt 0"},
            {"type": "user", "text": "prompt 1"},
        ]
        app.sm.get.return_value = session_mock

        async def push_screen_mock(screen, callback):
            res = callback(RewindSelection(index=0, restore_code=False))
            if inspect.isawaitable(res):
                await res

        app.push_screen = push_screen_mock

        cmd = RewindCommand()
        await cmd.execute(app)

        # Pending fork must be cancelled
        self.assertIsNone(app.pending_fork)
        # UI reset called for turn 0
        chat_view.reset_to_messages.assert_called()

    async def test_fork_then_rewind_cancel_preserves_pending_fork(self):
        import inspect

        from widgets.presentation.commands import RewindCommand

        app = MagicMock()
        chat_view = MagicMock()
        chat_view.get_user_messages.return_value = [(10, "prompt 0"), (20, "prompt 1")]
        chat_input = MagicMock()
        app.query_one.side_effect = lambda target, *args, **kwargs: chat_input if "#message-input" in str(target) else chat_view
        app.current_session_id = "orig_sid"
        app.pending_fork = {"parent_session_id": "orig_sid", "up_to_msg_index": 1, "title": "fork"}

        session_mock = MagicMock()
        session_mock.messages = [
            {"type": "user", "text": "prompt 0"},
            {"type": "user", "text": "prompt 1"},
        ]
        app.sm.get.return_value = session_mock

        async def push_screen_mock(screen, callback):
            # User dismissed modal (Esc / Current state)
            res = callback(None)
            if inspect.isawaitable(res):
                await res

        app.push_screen = push_screen_mock

        cmd = RewindCommand()
        await cmd.execute(app)

        # Pending fork must still be preserved
        self.assertEqual(app.pending_fork, {"parent_session_id": "orig_sid", "up_to_msg_index": 1, "title": "fork"})
        chat_input.focus.assert_called()

    async def test_fork_command_truncates_unloaded_messages(self):
        from unittest.mock import AsyncMock

        app = MagicMock()
        chat_view = MagicMock()
        chat_view.PAGE_SIZE = 50
        chat_view.reset_to_messages = AsyncMock()
        app.query_one.return_value = chat_view
        app.current_session_id = "orig_sid"

        parent_sess = MagicMock()
        parent_sess.title = "Parent Title"
        parent_sess.messages = [
            {"type": "user", "text": f"prompt {i}"} for i in range(10)
        ]
        app.sm.get.return_value = parent_sess

        chat_input = MagicMock()
        chat_input.text = "prompt 2"

        def query_one_mock(target, *args, **kwargs):
            if target == "#message-input" or "ChatInput" in str(args):
                return chat_input
            return chat_view

        app.query_one = query_one_mock

        cmd = ForkCommand()
        await cmd.execute(app)
        await self._apply_selection(app, 2)

        # reset_to_messages must receive only messages before turn 2 (turns 0 and 1)
        chat_view.reset_to_messages.assert_called_once()
        passed_msgs = chat_view.reset_to_messages.call_args[0][0]
        self.assertEqual(len(passed_msgs), 2)
        self.assertEqual(passed_msgs[0]["text"], "prompt 0")
        self.assertEqual(passed_msgs[1]["text"], "prompt 1")
