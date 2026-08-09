import unittest
from unittest.mock import MagicMock

from core.background_task import BackgroundTask
from tools.manage_shell import ManageShellTool


class TestManageShellTool(unittest.IsolatedAsyncioTestCase):

    def _make_app(self, tasks=None):
        mock_app = MagicMock()
        mock_app.background_tasks = tasks if tasks is not None else []
        return mock_app

    async def test_list_no_tasks(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "list"}, app=mock_app)
        self.assertIn("OK: no tasks active", res)

    async def test_list_scoped_to_current_session(self):
        tool = ManageShellTool()
        t1 = BackgroundTask("t1", "echo hi", MagicMock())
        t1.session_id = "sess-A"
        t2 = BackgroundTask("t2", "ls -la", MagicMock())
        t2.session_id = "sess-B"
        mock_app = self._make_app([t1, t2])
        mock_app.current_session_id = "sess-A"
        res = await tool.execute({"action": "list"}, app=mock_app)
        self.assertIn("t1", res)
        self.assertIn("echo hi", res)
        self.assertNotIn("t2", res)
        self.assertNotIn("ls -la", res)

    async def test_list_with_tasks(self):
        tool = ManageShellTool()
        t1 = BackgroundTask("t1", "echo hello", MagicMock())
        t2 = BackgroundTask("t2", "ls -la", MagicMock())
        t2.is_running = False
        mock_app = self._make_app([t1, t2])
        res = await tool.execute({"action": "list"}, app=mock_app)
        self.assertIn("Active Background Tasks", res)
        self.assertIn("t1", res)
        self.assertIn("RUNNING", res)
        self.assertIn("t2", res)
        self.assertIn("FINISHED", res)

    async def test_status_missing_task_id(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "status"}, app=mock_app)
        self.assertIn("ERR", res)
        self.assertIn("task_id", res)

    async def test_status_task_not_found(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "status", "task_id": "ghost"}, app=mock_app)
        self.assertIn("ERR: task 'ghost' not found", res)

    async def test_status_running_task(self):
        tool = ManageShellTool()
        t = BackgroundTask("t-run", "npm build", MagicMock())
        t.output = ["Building...\n", "Done\n"]
        mock_app = self._make_app([t])
        res = await tool.execute({"action": "status", "task_id": "t-run"}, app=mock_app)
        self.assertIn("t-run", res)
        self.assertIn("RUNNING", res)
        self.assertIn("npm build", res)
        self.assertIn("Building...", res)

    async def test_status_truncates_long_output(self):
        tool = ManageShellTool()
        t = BackgroundTask("t-big", "big cmd", MagicMock())
        t.output = ["x" * 5000]
        mock_app = self._make_app([t])
        res = await tool.execute({"action": "status", "task_id": "t-big"}, app=mock_app)
        self.assertIn("truncated", res)

    async def test_kill_missing_task_id(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "kill"}, app=mock_app)
        self.assertIn("ERR", res)
        self.assertIn("task_id", res)

    async def test_kill_task_not_found(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "kill", "task_id": "ghost"}, app=mock_app)
        self.assertIn("ERR: task 'ghost' not found", res)

    async def test_kill_running_task(self):
        tool = ManageShellTool()
        mock_proc = MagicMock()
        t = BackgroundTask("t-kill", "sleep 100", mock_proc)
        t.kill = MagicMock(return_value=_noop_async())
        mock_app = self._make_app([t])
        res = await tool.execute({"action": "kill", "task_id": "t-kill"}, app=mock_app)
        self.assertIn("OK: t-kill killed", res)
        self.assertFalse(t.is_running)

    async def test_kill_not_running_task(self):
        tool = ManageShellTool()
        t = BackgroundTask("t-done", "echo hi", MagicMock())
        t.is_running = False
        mock_app = self._make_app([t])
        res = await tool.execute({"action": "kill", "task_id": "t-done"}, app=mock_app)
        self.assertIn("not running", res)

    async def test_unknown_action(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "bogus"}, app=mock_app)
        self.assertIn("ERR: unknown action 'bogus'", res)
        self.assertIn("bogus", res)

    async def test_no_task_manager_no_app(self):
        tool = ManageShellTool()
        res = await tool.execute({"action": "list"})
        self.assertIn("ERR: no task manager", res)


async def _noop_async():
    return None


if __name__ == "__main__":
    unittest.main()
