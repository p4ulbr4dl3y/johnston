import unittest
from unittest.mock import MagicMock

from core.infrastructure.tasks.manager import TaskManager
from core.infrastructure.tasks.shell_task import ShellTask
from core.infrastructure.tasks.task import TaskStatus
from tools.manage_shell import ManageShellTool


def _make_task(task_id, command="cmd", status=None, output=None, proc=None):
    t = ShellTask(task_id, command, proc)
    t.session_id = getattr(t, "session_id", "sess-A")
    t.is_background = True
    if status is not None:
        t.status = status
    if output:
        for line in output:
            t.output.append(line)
    return t


class TestManageShellTool(unittest.IsolatedAsyncioTestCase):
    def _make_app(self, tasks=None):
        mock_app = MagicMock()
        mock_app.current_session_id = None
        mgr = TaskManager()
        for t in tasks or []:
            mgr.register(t)
        mock_app.task_manager = mgr
        return mock_app

    async def test_list_no_tasks(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "list"}, ctx=mock_app)
        self.assertIn("no tasks active", res)

    async def test_list_scoped_to_current_session(self):
        tool = ManageShellTool()
        t1 = _make_task("t1", "echo hi")
        t1.session_id = "sess-A"
        t2 = _make_task("t2", "ls -la")
        t2.session_id = "sess-B"
        mock_app = self._make_app([t1, t2])
        mock_app.current_session_id = "sess-A"
        res = await tool.execute({"action": "list"}, ctx=mock_app)
        self.assertIn("t1", res)
        self.assertIn("echo hi", res)
        self.assertNotIn("t2", res)
        self.assertNotIn("ls -la", res)

    async def test_list_with_tasks(self):
        tool = ManageShellTool()
        t1 = _make_task("t1", "echo hello")
        t2 = _make_task("t2", "ls -la", status=TaskStatus.COMPLETED)
        mock_app = self._make_app([t1, t2])
        res = await tool.execute({"action": "list"}, ctx=mock_app)
        self.assertIn("Active Background Tasks", res)
        self.assertIn("t1", res)
        self.assertIn("RUNNING", res)
        self.assertIn("t2", res)
        self.assertIn("FINISHED", res)

    async def test_status_missing_task_id(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "status"}, ctx=mock_app)
        self.assertIn("ERR", res)
        self.assertIn("task_id", res)

    async def test_status_task_not_found(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "status", "task_id": "ghost"}, ctx=mock_app)
        self.assertIn("ERR: notfound 'ghost'", res)

    async def test_status_running_task(self):
        tool = ManageShellTool()
        t = _make_task("t-run", "npm build", output=["Building...\n", "Done\n"])
        mock_app = self._make_app([t])
        res = await tool.execute({"action": "status", "task_id": "t-run"}, ctx=mock_app)
        self.assertIn("t-run", res)
        self.assertIn("RUNNING", res)
        self.assertIn("npm build", res)
        self.assertIn("Building...", res)

    async def test_status_includes_log_path(self):
        tool = ManageShellTool()
        t = _make_task("t-log", "npm build", output=["Building...\n"])
        t.log_path = "/fake/logs/out.log"
        mock_app = self._make_app([t])
        res = await tool.execute({"action": "status", "task_id": "t-log"}, ctx=mock_app)
        self.assertIn("Full Output Log", res)
        self.assertIn("/fake/logs/out.log", res)

    async def test_status_truncates_long_output(self):
        tool = ManageShellTool()
        t = _make_task("t-big", "big cmd", output=["x" * 5000])
        mock_app = self._make_app([t])
        res = await tool.execute({"action": "status", "task_id": "t-big"}, ctx=mock_app)
        self.assertIn("truncated", res)

    async def test_kill_missing_task_id(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "kill"}, ctx=mock_app)
        self.assertIn("ERR", res)
        self.assertIn("task_id", res)

    async def test_kill_task_not_found(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "kill", "task_id": "ghost"}, ctx=mock_app)
        self.assertIn("ERR: notfound 'ghost'", res)

    async def test_kill_running_task(self):
        tool = ManageShellTool()
        mock_proc = MagicMock()
        t = _make_task("t-kill", "sleep 100", proc=mock_proc)

        async def _fake_kill():
            t.status = TaskStatus.KILLED

        t.kill = _fake_kill
        mock_app = self._make_app([t])
        res = await tool.execute({"action": "kill", "task_id": "t-kill"}, ctx=mock_app)
        self.assertIn("t-kill killed", res)
        self.assertFalse(t.is_running)

    async def test_kill_not_running_task(self):
        tool = ManageShellTool()
        t = _make_task("t-done", "echo hi", status=TaskStatus.COMPLETED)
        mock_app = self._make_app([t])
        res = await tool.execute({"action": "kill", "task_id": "t-done"}, ctx=mock_app)
        self.assertIn("ERR: notrunning", res)

    async def test_unknown_action(self):
        tool = ManageShellTool()
        mock_app = self._make_app([])
        res = await tool.execute({"action": "bogus"}, ctx=mock_app)
        self.assertIn("ERR: action 'bogus'", res)
        self.assertIn("bogus", res)

    async def test_no_task_manager_no_app(self):
        tool = ManageShellTool()
        res = await tool.execute({"action": "list"})
        self.assertIn("ERR: manager 'none'", res)


async def _noop_async():
    return None


if __name__ == "__main__":
    unittest.main()
