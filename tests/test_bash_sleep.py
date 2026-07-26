import unittest
from unittest.mock import MagicMock, patch

from tools.bash import BashTool, _new_task_id
from tools.context import ToolContext


class TestBashSmartSleep(unittest.IsolatedAsyncioTestCase):
    def test_task_ids_are_unique_with_same_timestamp(self):
        with patch("tools.bash.time.time_ns", return_value=123):
            first = _new_task_id()
            second = _new_task_id()

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("bash_123_"))
        self.assertTrue(second.startswith("bash_123_"))

    async def test_pure_sleep(self):
        tool = BashTool()
        mock_app = MagicMock()
        mock_app.tool_context = ToolContext(mock_app)

        res = await tool.execute({"command": "sleep 0.05"}, app=mock_app)
        self.assertIn("Slept for 0.05 seconds", res)

    async def test_sleep_chain(self):
        tool = BashTool()
        mock_app = MagicMock()
        mock_app.tool_context = ToolContext(mock_app)

        res = await tool.execute({"command": "sleep 0.05 && echo 'done'"}, app=mock_app)
        self.assertIn("done", res)
