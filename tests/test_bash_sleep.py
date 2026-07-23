import unittest
from unittest.mock import MagicMock

from tools.bash import BashTool
from tools.context import ToolContext


class TestBashSmartSleep(unittest.IsolatedAsyncioTestCase):
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
