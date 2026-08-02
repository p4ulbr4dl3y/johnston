import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.shell import ShellTool, _new_task_id


class TestShellTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = ShellTool()

    def test_new_task_id(self):
        tid1 = _new_task_id()
        tid2 = _new_task_id()
        self.assertTrue(tid1.startswith("shell_"))
        self.assertNotEqual(tid1, tid2)

    async def test_sleep_chain_no_remainder(self):
        res = await self.tool.execute({"command": "sleep 0.001"})
        self.assertEqual(res, "Slept for 0.001 seconds.")

    async def test_sleep_chain_with_remainder(self):
        res = await self.tool.execute({"command": "sleep 0.001 && echo after_sleep"})
        self.assertIn("after_sleep", res)

    async def test_shell_safety_check_rejected(self):
        mock_app = MagicMock()

        def push_screen_side_effect(screen, callback):
            callback(False)

        mock_app.push_screen.side_effect = push_screen_side_effect

        with patch("core.shell_guard.analyze_shell_command", return_value=(False, "Destructive command")):
            res = await self.tool.execute({"command": "rm -rf /"}, app=mock_app)
            self.assertEqual(res, "Command execution rejected by user.")

    async def test_shell_safety_check_confirmed(self):
        mock_app = MagicMock()

        def push_screen_side_effect(screen, callback):
            callback(True)

        mock_app.push_screen.side_effect = push_screen_side_effect

        with patch("core.shell_guard.analyze_shell_command", return_value=(False, "Destructive command")):
            res = await self.tool.execute({"command": "echo confirmed"}, app=mock_app)
            self.assertIn("confirmed", res)

    async def test_shell_safety_check_exception(self):
        mock_app = MagicMock()
        mock_app.push_screen.side_effect = RuntimeError("Screen push failed")

        with patch("core.shell_guard.analyze_shell_command", return_value=(False, "Destructive command")):
            res = await self.tool.execute({"command": "rm -rf /"}, app=mock_app)
            self.assertIn("Error prompting for command permission: Screen push failed", res)

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
            patch("asyncio.create_subprocess_shell", side_effect=RuntimeError("Subprocess launch failed")),
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
            patch("asyncio.create_subprocess_shell", return_value=mock_p),
            patch("tools.shell.BackgroundTask") as mock_bg_cls,
        ):
            mock_task = MagicMock()
            mock_task.read_task = dummy_task
            mock_task.get_formatted_output.return_value = "normal_timeout_output"
            mock_bg_cls.return_value = mock_task

            with patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for):
                res = await self.tool.execute({"command": "echo test"})
                self.assertIn("normal_timeout_output", res)

    async def test_normal_execution_empty_output(self):
        res = await self.tool.execute({"command": "true"})
        self.assertEqual(res, "Command executed with no output.")

    async def test_command_timeout_moved_to_background(self):
        mock_app = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.app = mock_app
        mock_ctx.is_subagent = False

        mock_p = MagicMock()

        def _mock_wait():
            fut = asyncio.Future()
            fut.set_result(0)
            return fut

        mock_p.wait = _mock_wait

        async def custom_wait_for(fut, timeout):
            if timeout == 60.0:
                raise asyncio.TimeoutError()
            return await fut

        with (
            patch("asyncio.create_subprocess_shell", return_value=mock_p),
            patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for),
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = await self.tool.execute({"command": "echo timeout_test"}, app=mock_app)
            self.assertIn("[Background Task ID:", res)
            self.assertIn("Command is running in background", res)
            mock_ctx.add_background_task.assert_called_once()
            mock_ctx.notify.assert_called_once()

    async def test_create_windows_process_powershell(self):
        with (
            patch("tools.shell.shell_executable", return_value="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"),
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
                **shell_subprocess_kwargs(),
            )

    async def test_subagent_shell_execution_success(self):
        mock_ctx = MagicMock()
        mock_ctx.is_subagent = True

        res = await self.tool.execute({"command": "echo subagent_test", "timeout": 10}, app=mock_ctx)
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
            patch("asyncio.create_subprocess_shell", return_value=mock_p),
            patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for),
            patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
            patch.object(ShellTool, "_ensure_context", return_value=mock_ctx),
        ):
            res = await self.tool.execute({"command": "run_long_task", "timeout": 5})
            self.assertIn("Error: Command timed out after 5 seconds and was terminated.", res)
            mock_term.assert_called_once()
            mock_ctx.add_background_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
