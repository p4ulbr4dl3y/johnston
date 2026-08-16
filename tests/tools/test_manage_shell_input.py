import unittest
from unittest.mock import MagicMock

from core.infrastructure.tasks.manager import TaskManager
from core.infrastructure.tasks.shell_task import ShellTask
from core.infrastructure.tasks.task import TaskStatus
from tools.context import ToolContext
from tools.manage_shell import ManageShellTool


class TestManageShellInput(unittest.IsolatedAsyncioTestCase):
    def _make_app(self, bg_task):
        mock_app = MagicMock()
        mgr = TaskManager()
        mgr.register(bg_task)
        mock_app.task_manager = mgr
        ctx = ToolContext(mock_app)
        mock_app.tool_context = ctx
        return mock_app

    async def test_manage_shell_send_input(self):
        async def dummy_drain():
            pass

        mock_proc = MagicMock()
        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = dummy_drain
        mock_proc.stdin = mock_stdin

        bg_task = ShellTask("task_interactive", "read name", mock_proc)

        tool = ManageShellTool()
        mock_app = self._make_app(bg_task)

        res = str(await tool.execute(
            {"action": "send_input", "task_id": "task_interactive", "input": "John Doe"}, ctx=mock_app
        ))
        self.assertIn("OK: input sent to task_interactive", res)
        mock_stdin.write.assert_called_once_with(b"John Doe\n")

    async def test_manage_shell_send_input_not_running(self):
        mock_proc = MagicMock()
        bg_task = ShellTask("task_finished", "echo hello", mock_proc)
        bg_task.status = TaskStatus.COMPLETED

        tool = ManageShellTool()
        mock_app = self._make_app(bg_task)

        res = str(await tool.execute({"action": "send_input", "task_id": "task_finished", "input": "test"}, ctx=mock_app))
        self.assertIn("ERR: notrunning 'task_finished'", res)
