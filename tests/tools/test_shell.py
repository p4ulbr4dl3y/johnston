import asyncio
import os
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.infrastructure.tasks.manager import TaskManager
from tools.shell import ShellTool, _new_task_id


class TestShellTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from core.permission_manager import PermissionManager

        PermissionManager.get_instance().clear_session_overrides()
        self.config_patcher = patch("core.permission_manager.CONFIG_FILE", "/nonexistent_test_config.json")
        self.config_patcher.start()
        self.tool = ShellTool()

    def tearDown(self):
        self.config_patcher.stop()

    def test_new_task_id(self):
        tid1 = _new_task_id()
        tid2 = _new_task_id()
        self.assertTrue(tid1.startswith("shell_"))
        self.assertNotEqual(tid1, tid2)

    async def test_sleep_chain_no_remainder(self):
        res = str(await self.tool.execute({"command": "sleep 0.001"}))
        self.assertEqual(res, "slept 0.001s")

    async def test_sleep_chain_with_remainder(self):
        res = str(await self.tool.execute({"command": "sleep 0.001 && echo after_sleep"}))
        self.assertIn("after_sleep", res)

    async def test_standard_pipe_execution(self):
        res = str(await self.tool.execute({"command": "echo std_pipe_test"}))
        self.assertIn("std_pipe_test", res)

    async def test_windows_execution_branch(self):
        mock_p = MagicMock()

        async def _mock_wait():
            return 0

        mock_p.wait = _mock_wait

        with (
            patch("tools.shell.is_windows", return_value=True),
            patch.object(ShellTool, "_create_windows_process", return_value=mock_p) as mock_win_proc,
        ):
            res = str(await self.tool.execute({"command": "dir"}))
            mock_win_proc.assert_called_once()
            self.assertIsNotNone(res)

    async def test_subprocess_creation_exception_cleanup_no_transport(self):
        with (
            patch("tools.shell.is_windows", return_value=False),
            patch.object(ShellTool, "_create_std_process", side_effect=RuntimeError("Subprocess launch failed")),
        ):
            with self.assertRaises(RuntimeError):
                await self.tool.execute({"command": "echo fail"})

    async def test_main_sync_read_task_drain_timeout(self):
        # Main agent synchronous path: process finishes, but draining the read
        # task times out -> ignored, output still returned.
        mock_ctx = MagicMock()
        mock_ctx.is_subagent = False

        mock_p = MagicMock()

        async def _mock_wait():
            return 0

        mock_p.wait = _mock_wait

        async def custom_wait_for(fut, timeout):
            if timeout == 2.0:
                raise asyncio.TimeoutError()
            return await fut

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = str(await self.tool.execute({"command": "echo test"}))
        self.assertEqual(res, "(no output)")

    async def test_normal_execution_empty_output(self):
        # `true` is POSIX-only; `cd .` produces no output on both cmd/PowerShell and sh.
        res = str(await self.tool.execute({"command": "true" if os.name != "nt" else "cd ."}))
        self.assertEqual(res, "(no output)")

    async def test_command_timeout_terminates_process(self):
        mock_app = MagicMock()
        mock_app.task_manager = TaskManager()
        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.is_subagent = False
        mock_ctx.task_manager = mock_app.task_manager
        mock_ctx.add_background_task.side_effect = lambda t: mock_app.task_manager.register(t)

        mock_p = MagicMock()
        mock_p.wait.return_value = asyncio.Future()
        mock_p.returncode = None

        with (
            patch("tools.shell.shell_executable", return_value="/bin/sh"),
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = str(await self.tool.execute({"command": "run_long_task", "timeout": 1}, ctx=mock_app))
            self.assertIn("ERR: timeout 'shell': timed out after 1s", res)
            self.assertNotIn("moved to background.", res)
            mock_term.assert_called_once()
            # Sync tasks are temporarily registered (for ctrl+b) even on timeout;
            # they are NOT converted to persistent background tasks, so the
            # manager must not still hold them after the tool returns.
            mock_ctx.add_background_task.assert_called_once()
            self.assertEqual(len([t for t in mock_app.task_manager]), 0)

    async def test_create_windows_process_powershell(self):
        with (
            patch(
                "tools.shell.shell_executable",
                return_value="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
            ),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            await self.tool._create_windows_process("Get-Process", {"ENV": "1"})
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            self.assertEqual(args[0], "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe")
            self.assertIn("-NoProfile", args)

    async def test_create_windows_process_cmd(self):
        with (
            patch("tools.shell.shell_executable", return_value="C:\\Windows\\System32\\cmd.exe"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            await self.tool._create_windows_process("dir", {"ENV": "1"})
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            self.assertEqual(args[0], "C:\\Windows\\System32\\cmd.exe")
            self.assertIn("/c", args)

    async def test_create_windows_process_default_shell(self):
        with (
            patch("tools.shell.shell_executable", return_value="/bin/sh"),
            patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell,
        ):
            from core.infrastructure.platform.platform_utils import shell_subprocess_kwargs

            await self.tool._create_windows_process("echo 1", {"ENV": "1"})
            mock_shell.assert_called_once_with(
                "echo 1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={"ENV": "1"},
                cwd=None,
                **shell_subprocess_kwargs(),
            )

    async def test_subagent_shell_execution_success(self):
        mock_ctx = MagicMock()
        mock_ctx.is_subagent = True

        res = str(await self.tool.execute({"command": "echo subagent_test", "timeout": 10}, ctx=mock_ctx))
        self.assertIn("subagent_test", res)
        mock_ctx.add_background_task.assert_not_called()

    async def test_subagent_shell_execution_timeout(self):
        mock_ctx = MagicMock()
        mock_ctx.is_subagent = True

        mock_p = MagicMock()

        def _mock_wait():
            fut = asyncio.Future()
            fut.set_result(0)
            return fut

        mock_p.wait = _mock_wait

        async def custom_wait_for(fut, timeout):
            if timeout == 5.0:
                raise asyncio.TimeoutError()
            return await fut

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for),
            patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = str(await self.tool.execute({"command": "run_long_task", "timeout": 5}))
            self.assertIn("ERR: timeout 'shell': timed out after 5s", res)
            mock_term.assert_called_once()
            mock_ctx.add_background_task.assert_called_once()

    async def test_explicit_run_in_background(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()

        with (
            patch("tools.shell.shell_executable", return_value="/bin/sh"),
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = str(await self.tool.execute({"command": "tail -f log.txt", "background": True}, ctx=mock_app))
            self.assertIn("[Background Task ID:", res)
            self.assertIn("moved to background.", res)
            mock_ctx.add_background_task.assert_called_once()

    async def test_subagent_explicit_run_in_background_rejected(self):
        mock_ctx = MagicMock()
        mock_ctx.is_subagent = True

        mock_p = MagicMock()

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = str(await self.tool.execute({"command": "tail -f log.txt", "background": True}))
            self.assertIn("ERR: background 'shell'", res)
            mock_term.assert_called_once()
            mock_ctx.add_background_task.assert_not_called()

    async def test_main_sync_not_registered_as_background_task(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()
        mock_p.stdout = None

        async def _mock_wait():
            return 0

        mock_p.wait = _mock_wait

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = str(await self.tool.execute({"command": "echo sync"}, ctx=mock_app))
            self.assertEqual(res, "(no output)")
            # Sync task is registered while running for ctrl+b, then dropped
            # after completion (never converted to a background task).
            mock_ctx.add_background_task.assert_called_once()

    async def test_sync_task_cleaned_up_from_background_tasks(self):
        mock_app = MagicMock()
        mock_app.task_manager = TaskManager()
        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.is_subagent = False
        mock_ctx.task_manager = mock_app.task_manager
        mock_ctx.add_background_task.side_effect = lambda t: mock_app.task_manager.register(t)

        with patch.object(ShellTool, "_ensure_context", return_value=mock_ctx):
            res = str(await self.tool.execute({"command": "echo test_sync_cleanup"}, ctx=mock_app))
            self.assertIn("test_sync_cleanup", res)
            # Sync task should be dropped from the manager after finishing
            self.assertEqual(len([t for t in mock_app.task_manager]), 0)

    async def test_invalid_timeout_value_falls_back_to_default(self):
        res = str(await self.tool.execute({"command": "echo hi", "timeout": "abc"}))
        self.assertIn("hi", res)

    async def test_sleep_chain_exceeds_timeout(self):
        res = str(await self.tool.execute({"command": "sleep 5", "timeout": 1}))
        self.assertEqual(res, "ERR: reject: sleep 5.0s exceeds timeout 1s")

    async def test_subagent_no_stdout_stream(self):
        # p.stdout is None -> the stream reader exits immediately and empty
        # output is reported instead of hanging.
        mock_ctx = MagicMock()
        mock_ctx.is_subagent = True

        mock_p = MagicMock()
        mock_p.stdout = None

        def _mock_wait():
            fut = asyncio.Future()
            fut.set_result(0)
            return fut

        mock_p.wait = _mock_wait

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = str(await self.tool.execute({"command": "true"}, ctx=mock_ctx))
        self.assertEqual(res, "(no output)")

    async def test_subagent_read_task_drain_timeout(self):
        # Process finishes, but draining the read task times out -> ignored.
        mock_ctx = MagicMock()
        mock_ctx.is_subagent = True

        mock_p = MagicMock()
        mock_p.stdout = None

        def _mock_wait():
            fut = asyncio.Future()
            fut.set_result(0)
            return fut

        mock_p.wait = _mock_wait

        async def custom_wait_for(fut, timeout):
            if timeout == 2.0:
                raise asyncio.TimeoutError()
            return await fut

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = str(await self.tool.execute({"command": "true"}, ctx=mock_ctx))
        self.assertEqual(res, "(no output)")

    async def test_subagent_timeout_read_task_exception_ignored(self):
        # Subagent timeout path: draining the read task after kill raises a
        # non-Timeout exception -> swallowed, partial output still reported.
        mock_ctx = MagicMock()
        mock_ctx.is_subagent = True

        mock_p = MagicMock()
        mock_p.stdout = None

        def _mock_wait():
            return asyncio.Future()  # never resolves

        mock_p.wait = _mock_wait

        async def custom_wait_for(fut, timeout):
            if timeout == 5.0:
                raise asyncio.TimeoutError()
            raise RuntimeError("drain failed")

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for),
            patch("tools.shell.terminate_process", new_callable=AsyncMock),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = str(await self.tool.execute({"command": "run_long_task", "timeout": 5}))
        self.assertIn("ERR: timeout 'shell': timed out after 5s", res)

    async def test_subagent_shell_execution_cancelled(self):
        mock_ctx = MagicMock()
        mock_ctx.is_subagent = True

        mock_p = MagicMock()
        mock_p.stdout = None

        wait_invoked = asyncio.Event()

        def _mock_wait():
            wait_invoked.set()
            return asyncio.Future()  # never resolves

        mock_p.wait = _mock_wait

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            exec_task = asyncio.create_task(self.tool.execute({"command": "run_long_task"}))
            await asyncio.wait_for(wait_invoked.wait(), timeout=5.0)
            exec_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await exec_task
            mock_term.assert_called_once()

    async def test_main_sync_timeout_with_output(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()
        mock_p.wait.return_value = asyncio.Future()

        async def custom_wait_for(fut, timeout):
            if timeout == 1.0:
                raise asyncio.TimeoutError()
            return await fut

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for),
            patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = str(await self.tool.execute({"command": "tail -f x", "timeout": 1}))
            self.assertIn("ERR: timeout 'shell': timed out after 1s", res)
            mock_term.assert_called_once()
            mock_ctx.add_background_task.assert_called_once()


    async def test_execute_cancelled_terminates_process(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()
        mock_p.wait.return_value = asyncio.Future()

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            exec_task = asyncio.create_task(self.tool.execute({"command": "tail -f log.txt"}))
            await asyncio.sleep(0.05)
            exec_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await exec_task
            mock_term.assert_called_once()
            mock_ctx.add_background_task.assert_called_once()

    async def test_main_sync_task_visible_and_running_while_alive(self):
        # While a sync shell runs, it must be visible in the task manager and
        # report is_running=True (process still alive) so ctrl+b / manage_shell
        # can act on it; after completion it must be dropped.
        mock_app = MagicMock()
        mock_app.task_manager = TaskManager()
        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.is_subagent = False
        mock_ctx.task_manager = mock_app.task_manager
        mock_ctx.add_background_task.side_effect = lambda t: mock_app.task_manager.register(t)

        mock_p = MagicMock()
        mock_p.stdout = None
        mock_p.wait.return_value = asyncio.Future()  # never resolves
        mock_p.returncode = None

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
            patch("tools.shell.terminate_process", new_callable=AsyncMock),
        ):
            exec_task = asyncio.create_task(self.tool.execute({"command": "long_running_sync_cmd"}, ctx=mock_app))
            await asyncio.sleep(0.05)
            tasks = [t for t in mock_app.task_manager]
            self.assertEqual(len(tasks), 1)
            self.assertTrue(tasks[0].is_running)
            self.assertFalse(tasks[0].is_background)
            exec_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await exec_task
        self.assertEqual(len([t for t in mock_app.task_manager]), 0)

    async def test_background_task_manage_shell_lifecycle(self):
        # Real end-to-end: explicit background task (cat keeps stdin/stdout
        # open). manage_shell must list it as RUNNING (process alive), send
        # input to its stdin, and kill it.
        mock_app = MagicMock()
        mock_app.task_manager = TaskManager()
        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.is_subagent = False
        mock_ctx.task_manager = mock_app.task_manager
        mock_ctx.add_background_task.side_effect = lambda t: mock_app.task_manager.register(t)

        from tools.manage_shell import ManageShellTool

        mgr = ManageShellTool()
        with patch.object(ShellTool, "_ensure_context", return_value=mock_ctx):
            res = str(await self.tool.execute({"command": "cat", "background": True}, ctx=mock_app))
        m = re.search(r"Task ID: (shell_\d+_\d+)", res)
        self.assertIsNotNone(m)
        task_id = m.group(1)

        tasks = [t for t in mock_app.task_manager]
        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0].is_background)

        # list: process alive -> RUNNING
        r = str(await mgr.execute({"action": "list"}, ctx=mock_ctx))
        self.assertIn("RUNNING", r)
        self.assertIn(task_id, r)

        # send_input: writes to live stdin
        r = str(await mgr.execute({"action": "send_input", "task_id": task_id, "input": "hello_manage"}, ctx=mock_ctx))
        self.assertIn("OK: input sent", r)
        await asyncio.sleep(0.3)

        # background output is streamed into the task buffer (file log too)
        streamed = tasks[0].output.formatted()
        self.assertIn("hello_manage", streamed)

        # kill: terminates the live process
        r = str(await mgr.execute({"action": "kill", "task_id": task_id}, ctx=mock_ctx))
        self.assertIn("killed", r)

        # completed/killed task no longer reports running
        r = str(await mgr.execute({"action": "list"}, ctx=mock_ctx))
        self.assertIn("FINISHED", r)

    async def test_session_override_allow_shell(self):
        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        pm.clear_session_overrides()
        pm.set_session_override("shell", "allow")

        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(return_value=True)

        res = str(await self.tool.execute({"command": "echo session_allowed"}, ctx=mock_app))
        self.assertIn("session_allowed", res)
        pm.clear_session_overrides()

    def test_shell_get_schema_main(self):
        schema = self.tool.get_schema(is_subagent=False)
        params = schema["function"]["parameters"]["properties"]
        self.assertIn("background", params)
        self.assertIn("command", params)
        self.assertIn("timeout", params)

    def test_shell_get_schema_subagent(self):
        schema = self.tool.get_schema(is_subagent=True)
        params = schema["function"]["parameters"]["properties"]
        self.assertNotIn("background", params)
        self.assertIn("command", params)
        self.assertIn("timeout", params)
        self.assertIn("synchronous", schema["function"]["description"].lower())


if __name__ == "__main__":
    unittest.main()
