import unittest
from unittest.mock import MagicMock

from core.background_task import BackgroundTask
from tools.context import ToolContext
from tools.manage_shell import ManageShellTool


class TestManageShellInput(unittest.IsolatedAsyncioTestCase):
    async def test_manage_shell_send_input(self):
        async def dummy_drain():
            pass

        mock_proc = MagicMock()
        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = dummy_drain
        mock_proc.stdin = mock_stdin

        bg_task = BackgroundTask("task_interactive", "read name", mock_proc)

        tool = ManageShellTool()
        mock_app = MagicMock()
        mock_app.background_tasks = [bg_task]
        ctx = ToolContext(mock_app)
        mock_app.tool_context = ctx

        res = await tool.execute({"action": "send_input", "task_id": "task_interactive", "input": "John Doe"}, app=mock_app)
        self.assertIn("OK: input sent to task_interactive", res)
        mock_stdin.write.assert_called_once_with(b"John Doe\n")

    async def test_manage_shell_send_input_not_running(self):
        mock_proc = MagicMock()
        bg_task = BackgroundTask("task_finished", "echo hello", mock_proc)
        bg_task.is_running = False

        tool = ManageShellTool()
        mock_app = MagicMock()
        mock_app.background_tasks = [bg_task]
        ctx = ToolContext(mock_app)
        mock_app.tool_context = ctx

        res = await tool.execute({"action": "send_input", "task_id": "task_finished", "input": "test"}, app=mock_app)
        self.assertIn("ERR: notrunning 'task_finished'", res)
