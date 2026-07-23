import unittest
from unittest.mock import AsyncMock, MagicMock

from app import JohnstonChatApp


class TestDirectBashCommand(unittest.IsolatedAsyncioTestCase):
    async def test_direct_bash_command_execution(self):
        app = JohnstonChatApp()
        mock_chat_view = MagicMock()
        mock_tool_widget = MagicMock()
        mock_chat_view.add_user_message = AsyncMock()
        mock_chat_view.add_tool_call = AsyncMock(return_value=mock_tool_widget)

        app.query_one = MagicMock(return_value=mock_chat_view)
        app.agent = MagicMock()
        app.agent.history = []
        app.save_current_session = MagicMock()

        # Run execute_direct_bash_command worker
        worker = app.execute_direct_bash_command("echo hello_direct")
        await worker.wait()

        mock_chat_view.add_user_message.assert_not_called()
        mock_chat_view.add_tool_call.assert_called_once_with("bash", "echo hello_direct")
        mock_tool_widget.set_result.assert_called_once()

        # Verify history updated
        self.assertEqual(len(app.agent.history), 2)
        self.assertIn("echo hello_direct", app.agent.history[0]["content"])
        self.assertIn("hello_direct", app.agent.history[1]["content"])
