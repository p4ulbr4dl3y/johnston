import unittest
from unittest.mock import AsyncMock, MagicMock

from app import JohnstonChatApp
from commands import handle_slash_command


class TestBashMode(unittest.IsolatedAsyncioTestCase):
    async def test_slash_bash_command_toggle(self):
        app = JohnstonChatApp()
        app.notify = MagicMock()
        app.refresh_status_footer = MagicMock()

        self.assertFalse(getattr(app, "bash_mode", False))

        # First toggle: ON
        handled = await handle_slash_command(app, "/bash")
        self.assertTrue(handled)
        self.assertTrue(app.bash_mode)
        app.notify.assert_called_with("Bash mode enabled (! prefix optional)")

        # Second toggle: OFF
        handled = await handle_slash_command(app, "/bash")
        self.assertTrue(handled)
        self.assertFalse(app.bash_mode)
        app.notify.assert_called_with("Bash mode disabled")

    async def test_direct_bash_no_user_message_block(self):
        app = JohnstonChatApp()
        mock_chat_view = MagicMock()
        mock_tool_widget = MagicMock()
        mock_chat_view.add_tool_call = AsyncMock(return_value=mock_tool_widget)
        mock_chat_view.add_user_message = AsyncMock()

        app.query_one = MagicMock(return_value=mock_chat_view)
        app.agent = MagicMock()
        app.agent.history = []
        app.save_current_session = MagicMock()

        worker = app.execute_direct_bash_command("ls")
        await worker.wait()

        # User message should NOT be printed
        mock_chat_view.add_user_message.assert_not_called()
        # Only tool widget should be printed
        mock_chat_view.add_tool_call.assert_called_once_with("bash", "ls")
        mock_tool_widget.set_result.assert_called_once()
