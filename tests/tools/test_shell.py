import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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
        res = await self.tool.execute({"command": "sleep 0.001"})
        self.assertEqual(res, "slept 0.001s")

    async def test_sleep_chain_with_remainder(self):
        res = await self.tool.execute({"command": "sleep 0.001 && echo after_sleep"})
        self.assertIn("after_sleep", res)

    async def test_shell_safety_check_rejected(self):
        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(return_value=False)

        with patch("core.shell_guard.analyze_shell_command", return_value=(False, "Destructive command")):
            res = await self.tool.execute({"command": "rm -rf /"}, ctx=mock_app)
            self.assertEqual(res, "ERR: denied 'shell': by user")

    async def test_shell_safety_check_confirmed(self):
        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(return_value=True)

        with patch("core.shell_guard.analyze_shell_command", return_value=(False, "Destructive command")):
            res = await self.tool.execute({"command": "echo confirmed"}, ctx=mock_app)
            self.assertIn("confirmed", res)

    async def test_shell_safety_check_exception(self):
        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(side_effect=RuntimeError("Screen push failed"))

        with patch("core.shell_guard.analyze_shell_command", return_value=(False, "Destructive command")):
            res = await self.tool.execute({"command": "rm -rf /"}, ctx=mock_app)
            self.assertIn("ERR: permission 'shell': Screen push failed", res)

    async def test_standard_pipe_execution(self):
        res = await self.tool.execute({"command": "echo std_pipe_test"})
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
            res = await self.tool.execute({"command": "dir"})
            mock_win_proc.assert_called_once()
            self.assertIsNotNone(res)

    async def test_subprocess_creation_exception_cleanup_no_transport(self):
        with (
            patch("tools.shell.is_windows", return_value=False),
            patch.object(ShellTool, "_create_std_process", side_effect=RuntimeError("Subprocess launch failed")),
        ):
            with self.assertRaises(RuntimeError):
                await self.tool.execute({"command": "echo fail"})

    async def test_normal_execution_read_task_timeout(self):
        mock_p = MagicMock()

        async def _mock_wait():
            return 0

        mock_p.wait = _mock_wait

        loop = asyncio.get_running_loop()
        dummy_task = loop.create_future()
        dummy_task.set_result(None)

        async def custom_wait_for(fut, timeout):
            if timeout == 2.0:
                raise asyncio.TimeoutError()
            return await fut

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.BackgroundTask") as mock_bg_cls,
        ):
            mock_task = MagicMock()
            mock_task.background_event = asyncio.Event()
            mock_task.read_task = dummy_task
            mock_task.get_formatted_output.return_value = "normal_timeout_output"
            mock_bg_cls.return_value = mock_task

            with patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for):
                res = await self.tool.execute({"command": "echo test"})
                self.assertIn("normal_timeout_output", res)

    async def test_normal_execution_empty_output(self):
        res = await self.tool.execute({"command": "true"})
        self.assertEqual(res, "(no output)")

    async def test_command_timeout_moved_to_background(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.app = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()

        def _mock_wait():
            return asyncio.Future()

        mock_p.wait = _mock_wait

        with (
            patch("tools.shell.shell_executable", return_value="/bin/sh"),
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = await self.tool.execute({"command": "echo timeout_test", "timeout": 1}, ctx=mock_app)
            self.assertIn("[Background Task ID:", res)
            self.assertIn("running:", res)
            mock_ctx.add_background_task.assert_called_once()

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
            from core.platform_utils import shell_subprocess_kwargs

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

        res = await self.tool.execute({"command": "echo subagent_test", "timeout": 10}, ctx=mock_ctx)
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
            res = await self.tool.execute({"command": "run_long_task", "timeout": 5})
            self.assertIn("ERR: timeout 'shell': timed out after 5s", res)
            mock_term.assert_called_once()
            mock_ctx.add_background_task.assert_not_called()

    async def test_explicit_run_in_background(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.app = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()

        with (
            patch("tools.shell.shell_executable", return_value="/bin/sh"),
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = await self.tool.execute({"command": "tail -f log.txt", "run_in_background": True}, ctx=mock_app)
            self.assertIn("[Background Task ID:", res)
            self.assertIn("running:", res)
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
            res = await self.tool.execute({"command": "tail -f log.txt", "run_in_background": True})
            self.assertIn("ERR: background 'shell'", res)
            mock_term.assert_called_once()
            mock_ctx.add_background_task.assert_not_called()

    async def test_move_to_background_during_execution(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.app = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()
        fut = asyncio.Future()
        mock_p.wait.return_value = fut

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            exec_task = asyncio.create_task(self.tool.execute({"command": "tail -f log.txt"}, ctx=mock_app))
            await asyncio.sleep(0.01)

            # Trigger backgrounding via move_to_background on registered task
            self.assertEqual(len(mock_ctx.add_background_task.call_args_list), 1)
            registered_bg_task = mock_ctx.add_background_task.call_args[0][0]
            registered_bg_task.move_to_background()

            res = await exec_task
            self.assertIn("[Background Task ID:", res)
            self.assertIn("running:", res)

    async def test_sync_task_cleaned_up_from_background_tasks(self):
        mock_app = MagicMock()
        mock_app.background_tasks = []
        mock_ctx = MagicMock()
        mock_ctx.app = mock_app
        mock_ctx.is_subagent = False
        mock_ctx.add_background_task.side_effect = lambda t: mock_app.background_tasks.append(t)

        with patch.object(ShellTool, "_ensure_context", return_value=mock_ctx):
            res = await self.tool.execute({"command": "echo test_sync_cleanup"}, ctx=mock_app)
            self.assertIn("test_sync_cleanup", res)
            # Sync task should be removed from app.background_tasks after finishing
            self.assertEqual(len(mock_app.background_tasks), 0)

    async def test_invalid_timeout_value_falls_back_to_default(self):
        res = await self.tool.execute({"command": "echo hi", "timeout": "abc"})
        self.assertIn("hi", res)

    async def test_sleep_chain_exceeds_timeout(self):
        res = await self.tool.execute({"command": "sleep 5", "timeout": 1})
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
            res = await self.tool.execute({"command": "true"}, ctx=mock_ctx)
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
            res = await self.tool.execute({"command": "true"}, ctx=mock_ctx)
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
            res = await self.tool.execute({"command": "run_long_task", "timeout": 5})
        self.assertIn("ERR: timeout 'shell': timed out after 5s", res)

    async def test_subagent_shell_execution_cancelled(self):
        mock_ctx = MagicMock()
        mock_ctx.is_subagent = True

        mock_p = MagicMock()
        mock_p.stdout = None

        def _mock_wait():
            return asyncio.Future()  # never resolves

        mock_p.wait = _mock_wait

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            exec_task = asyncio.create_task(self.tool.execute({"command": "run_long_task"}))
            await asyncio.sleep(0.01)
            exec_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await exec_task
            mock_term.assert_called_once()

    async def test_move_to_background_with_large_output_truncated(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.app = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()
        fut = asyncio.Future()
        mock_p.wait.return_value = fut

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            exec_task = asyncio.create_task(self.tool.execute({"command": "tail -f x"}))
            await asyncio.sleep(0.01)

            self.assertEqual(len(mock_ctx.add_background_task.call_args_list), 1)
            registered_bg_task = mock_ctx.add_background_task.call_args[0][0]
            registered_bg_task.output = ["y" * 2500]
            registered_bg_task.move_to_background()

            res = await exec_task
            self.assertIn("[Background Task ID:", res)
            self.assertIn("[Output truncated, showing last 2000 chars]", res)

    async def test_timeout_moved_to_background_with_output(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.app = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()
        mock_p.wait.return_value = asyncio.Future()

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            exec_task = asyncio.create_task(self.tool.execute({"command": "tail -f x", "timeout": 1}))
            await asyncio.sleep(0.01)

            self.assertEqual(len(mock_ctx.add_background_task.call_args_list), 1)
            registered_bg_task = mock_ctx.add_background_task.call_args[0][0]
            registered_bg_task.output = ["short output"]

            res = await exec_task
            self.assertIn("[Background Task ID:", res)
            self.assertIn("Recent Output:\nshort output", res)

    async def test_timeout_moved_to_background_with_large_output(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.app = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()
        mock_p.wait.return_value = asyncio.Future()

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            exec_task = asyncio.create_task(self.tool.execute({"command": "tail -f x", "timeout": 1}))
            await asyncio.sleep(0.01)

            self.assertEqual(len(mock_ctx.add_background_task.call_args_list), 1)
            registered_bg_task = mock_ctx.add_background_task.call_args[0][0]
            registered_bg_task.output = ["z" * 2500]

            res = await exec_task
            self.assertIn("[Background Task ID:", res)
            self.assertIn("[Output truncated, showing last 2000 chars]", res)

    async def test_normal_execution_read_task_drain_timeout(self):
        # is_background explicitly False so the sync completion branch (and its
        # 2s read_task drain timeout) is exercised.
        mock_p = MagicMock()

        async def _mock_wait():
            return 0

        mock_p.wait = _mock_wait

        loop = asyncio.get_running_loop()
        dummy_task = loop.create_future()
        dummy_task.set_result(None)

        async def custom_wait_for(fut, timeout):
            if timeout == 2.0:
                raise asyncio.TimeoutError()
            return await fut

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.BackgroundTask") as mock_bg_cls,
        ):
            mock_task = MagicMock()
            mock_task.background_event = asyncio.Event()
            mock_task.is_background = False
            mock_task.read_task = dummy_task
            mock_task.get_formatted_output.return_value = "drained_output"
            mock_bg_cls.return_value = mock_task

            with patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for):
                res = await self.tool.execute({"command": "echo test"})
                self.assertIn("drained_output", res)

    async def test_execute_cancelled_cleans_up_task(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.app = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()
        mock_p.wait.return_value = asyncio.Future()

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            exec_task = asyncio.create_task(self.tool.execute({"command": "tail -f log.txt"}))
            await asyncio.sleep(0.01)
            exec_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await exec_task

    async def test_execute_cancelled_with_falsy_task_kill_error(self):
        # Cancellation with a falsy BackgroundTask -> falls back to killing the
        # raw process, and a failing p.kill() must be swallowed.
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.app = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()
        mock_p.wait.return_value = asyncio.Future()
        mock_p.kill.side_effect = RuntimeError("kill failed")

        with (
            patch.object(ShellTool, "_create_std_process", return_value=mock_p),
            patch("tools.shell.BackgroundTask") as mock_bg_cls,
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            mock_bg = MagicMock()
            mock_bg.__bool__ = lambda self: False
            mock_bg.background_event = asyncio.Event()
            mock_bg_cls.return_value = mock_bg

            exec_task = asyncio.create_task(self.tool.execute({"command": "tail -f log.txt"}))
            await asyncio.sleep(0.01)
            exec_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await exec_task

    async def test_shell_safety_check_always_allow(self):
        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        pm.clear_session_overrides()

        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(return_value=True)

        with patch("core.shell_guard.analyze_shell_command", return_value=(False, "Destructive command")):
            res = await self.tool.execute({"command": "echo session_allowed"}, ctx=mock_app)
            self.assertIn("session_allowed", res)


if __name__ == "__main__":
    unittest.main()
