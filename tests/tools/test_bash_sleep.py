import unittest
from unittest.mock import MagicMock, patch

from tools.context import ToolContext
from tools.shell import ShellTool, _new_task_id


class TestShellSmartSleep(unittest.IsolatedAsyncioTestCase):
    def test_task_ids_are_unique_with_same_timestamp(self):
        with patch("tools.shell.time.time_ns", return_value=123):
            first = _new_task_id()
            second = _new_task_id()

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("shell_123_"))
        self.assertTrue(second.startswith("shell_123_"))

    async def test_pure_sleep(self):
        tool = ShellTool()
        mock_app = MagicMock()
        mock_app.tool_context = ToolContext(mock_app)

        res = await tool.execute({"command": "sleep 0.05"}, app=mock_app)
        self.assertIn("Slept for 0.05 seconds", res)

    async def test_sleep_chain(self):
        tool = ShellTool()
        mock_app = MagicMock()
        mock_app.tool_context = ToolContext(mock_app)

        res = await tool.execute({"command": "sleep 0.05 && echo 'done'"}, app=mock_app)
        self.assertIn("done", res)

    async def test_no_background_flag(self):
        tool = ShellTool()
        mock_app = MagicMock()
        mock_app.tool_context = ToolContext(mock_app)

        res = await tool.execute({"command": "echo 'nobg'", "no_background": True}, app=mock_app)
        self.assertIn("nobg", res)

    async def test_empty_output_command(self):
        tool = ShellTool()
        mock_app = MagicMock()
        mock_app.tool_context = ToolContext(mock_app)

        res = await tool.execute({"command": "true"}, app=mock_app)
        self.assertIn("Command executed with no output", res)

    async def test_unsafe_command_rejected_by_user(self):
        tool = ShellTool()
        mock_app = MagicMock()
        mock_app.tool_context = ToolContext(mock_app)

        def mock_push_screen(screen, callback=None):
            if callback:
                callback(False)

        mock_app.push_screen = mock_push_screen

        res = await tool.execute({"command": "rm -rf /"}, app=mock_app)
        self.assertIn("Command execution rejected by user", res)

    async def test_unsafe_command_accepted_by_user(self):
        tool = ShellTool()
        mock_app = MagicMock()
        mock_app.tool_context = ToolContext(mock_app)

        def mock_push_screen(screen, callback=None):
            if callback:
                callback(True)

        mock_app.push_screen = mock_push_screen

        res = await tool.execute({"command": "echo 'safe_accepted'"}, app=mock_app)
        self.assertIn("safe_accepted", res)


if __name__ == "__main__":
    unittest.main()

