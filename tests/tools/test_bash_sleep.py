import os
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

        cmd = "sleep 0.05" if os.name != "nt" else "cd ."
        res = await tool.execute({"command": cmd}, ctx=mock_app)
        self.assertIn('<cmd exit="0" elapsed=', res.content)
        self.assertEqual(res.display, "(no output)")

    async def test_sleep_chain(self):
        tool = ShellTool()
        mock_app = MagicMock()
        mock_app.tool_context = ToolContext(mock_app)

        cmd = "sleep 0.05 && echo 'done'" if os.name != "nt" else "echo done"
        res = str(await tool.execute({"command": cmd}, ctx=mock_app))
        self.assertIn("done", res)

    async def test_empty_output_command(self):
        tool = ShellTool()
        mock_app = MagicMock()
        mock_app.tool_context = ToolContext(mock_app)

        # `true` is POSIX-only; `cd .` produces no output on both cmd/PowerShell and sh.
        res = await tool.execute({"command": "true" if os.name != "nt" else "cd ."}, ctx=mock_app)
        self.assertIn('<cmd exit="0" elapsed=', res.content)
        self.assertEqual(res.display, "(no output)")


if __name__ == "__main__":
    unittest.main()
