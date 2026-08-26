import unittest
from unittest.mock import MagicMock

from widgets.commands import ForkCommand


class TestForkCommand(unittest.IsolatedAsyncioTestCase):
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

        forked_session = MagicMock()
        forked_session.id = "forked_sid"
        app.sm.fork_session.return_value = forked_session

        chat_input = MagicMock()
        chat_input.text = "prompt 0"

        def query_one_mock(target, *args, **kwargs):
            if target == "#message-input" or "ChatInput" in str(args):
                return chat_input
            return chat_view

        app.query_one = query_one_mock

        def push_screen_mock(screen, callback):
            callback(10)

        app.push_screen = push_screen_mock

        cmd = ForkCommand()
        await cmd.execute(app)

        app.sm.fork_session.assert_called_with("orig_sid", new_title="Parent Title (fork)", up_to_msg_index=0)
        app.load_session_ui.assert_called_with("forked_sid")
        chat_input.load_text.assert_called_with("prompt 0")
        chat_input.focus.assert_called()
        app.notify.assert_called_with("Session forked", severity="info")

    async def test_fork_command_successful_fork_turn_subsequent(self):
        app = MagicMock()
        chat_view = MagicMock()
        chat_view.get_user_messages.return_value = [(10, "prompt 0"), (20, "second turn prompt")]
        app.query_one.return_value = chat_view
        app.current_session_id = "orig_sid"

        forked_session = MagicMock()
        forked_session.id = "forked_sid"
        app.sm.fork_session.return_value = forked_session

        chat_input = MagicMock()
        chat_input.text = "second turn prompt"

        def query_one_mock(target, *args, **kwargs):
            if target == "#message-input" or "ChatInput" in str(args):
                return chat_input
            return chat_view

        app.query_one = query_one_mock

        def push_screen_mock(screen, callback):
            callback(20)

        app.push_screen = push_screen_mock

        cmd = ForkCommand()
        await cmd.execute(app)

        app.sm.fork_session.assert_called_with("orig_sid", new_title="second turn prompt", up_to_msg_index=1)
        app.load_session_ui.assert_called_with("forked_sid")
        chat_input.load_text.assert_called_with("second turn prompt")
