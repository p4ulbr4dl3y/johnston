import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.background_task import BackgroundTask, kill_all_background_tasks, process_carriage_returns, strip_ansi


class TestStripAnsi(unittest.TestCase):
    def test_no_ansi(self):
        self.assertEqual(strip_ansi("plain text"), "plain text")

    def test_simple_color_code(self):
        self.assertEqual(strip_ansi("\x1b[31mred\x1b[0m text"), "red text")

    def test_complex_escape(self):
        self.assertEqual(strip_ansi("\x1b[1;32;40mbold green\x1b[0m"), "bold green")

    def test_cursor_movement(self):
        self.assertEqual(strip_ansi("\x1b[2J\x1b[Hcleared"), "cleared")

    def test_empty_string(self):
        self.assertEqual(strip_ansi(""), "")


class TestProcessCarriageReturns(unittest.TestCase):
    def test_no_carriage_returns(self):
        self.assertEqual(process_carriage_returns("hello\nworld"), "hello\nworld")

    def test_simple_progress(self):
        self.assertEqual(process_carriage_returns("50%\r100%\n"), "100%\n")

    def test_multi_line_progress(self):
        raw = "Downloading 0%\rDownloading 50%\rDownloading 100%\nDone\n"
        self.assertEqual(process_carriage_returns(raw), "Downloading 100%\nDone\n")

    def test_empty_line_with_cr(self):
        self.assertEqual(process_carriage_returns("\r\r\n"), "\n")

    def test_preserves_non_cr_lines(self):
        self.assertEqual(process_carriage_returns("line1\nline2\nline3"), "line1\nline2\nline3")


class TestBackgroundTaskFormattedOutput(unittest.TestCase):
    def test_get_formatted_output_strips_ansi_and_cr(self):
        t = BackgroundTask("t1", "cmd", None)
        t.output = ["\x1b[32m50%\r100%\x1b[0m\n", "Done\n"]
        result = t.get_formatted_output()
        self.assertEqual(result, "100%\nDone\n")

    def test_get_formatted_output_empty(self):
        t = BackgroundTask("t2", "cmd", None)
        t.output = []
        self.assertEqual(t.get_formatted_output(), "")

    def test_get_formatted_output_chunks(self):
        bg_task = BackgroundTask("task_git", "git clone", None)
        bg_task.output = [
            "Receiving objects: 26% (127/485)\r",
            "Receiving objects: 27% (131/485)\r",
            "Receiving objects: 100% (485/485)\n",
            "Resolving deltas: 100% (17/17)\n"
        ]
        res = bg_task.get_formatted_output()
        self.assertEqual(res, "Receiving objects: 100% (485/485)\nResolving deltas: 100% (17/17)\n")


class TestBackgroundTaskSendInput(unittest.IsolatedAsyncioTestCase):
    async def test_send_input_not_running(self):
        t = BackgroundTask("t3", "cmd", None)
        t.is_running = False
        res = await t.send_input("hello")
        self.assertIn("not running", res)

    async def test_send_input_no_stdin_no_master_fd(self):
        t = BackgroundTask("t4", "cmd", MagicMock())
        t.is_running = True
        t.master_fd = None
        mock_proc = MagicMock()
        mock_proc.stdin = None
        t.process = mock_proc
        res = await t.send_input("hello")
        self.assertIn("stdin not writable", res)

    async def test_send_input_via_master_fd(self):
        t = BackgroundTask("t5", "cmd", None)
        t.is_running = True
        import os
        r_fd, w_fd = os.pipe()
        try:
            t.master_fd = w_fd
            res = await t.send_input("test input")
            self.assertIn("OK: input sent to t5", res)
            data = os.read(r_fd, 1024)
            self.assertEqual(data, b"test input\n")
        finally:
            os.close(r_fd)
            os.close(w_fd)

    async def test_start_reading_captures_unbuffered_prompts(self):
        mock_proc = MagicMock()
        mock_stdout = asyncio.StreamReader()
        mock_stdout.feed_data(b"How old are you? ")
        mock_stdout.feed_eof()
        mock_proc.stdout = mock_stdout

        t = BackgroundTask("t6", "cmd", mock_proc)
        t.start_reading(None, None)
        await t.read_task
        self.assertEqual(t.get_formatted_output(), "How old are you? ")


class TestBackgroundTaskLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_background_task_completion_callback(self):
        cb_called = False
        captured_res = ""

        def on_completed(task_id, cmd, res):
            nonlocal cb_called, captured_res
            cb_called = True
            captured_res = res

        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        reader = asyncio.StreamReader()
        reader.feed_data(b"Line 1\nLine 2\n")
        reader.feed_eof()
        mock_proc.stdout = reader

        bg_task = BackgroundTask("task_1", "echo test", mock_proc)
        bg_task.is_background = True
        read_task = bg_task.start_reading(app=None, on_completed_cb=on_completed)
        await read_task

        self.assertFalse(bg_task.is_running)
        self.assertTrue(cb_called)
        self.assertIn("Line 1\nLine 2\n", captured_res)

    async def test_background_task_kill(self):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        bg_task = BackgroundTask("task_2", "sleep 100", mock_proc)
        await bg_task.kill()

        self.assertFalse(bg_task.is_running)
        mock_proc.terminate.assert_called_once()
        self.assertIn("Task terminated by user", "".join(bg_task.output))

    async def test_background_task_send_input(self):
        mock_proc = MagicMock()
        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock(return_value=None)
        mock_proc.stdin = mock_stdin

        bg_task = BackgroundTask("task_3", "interactive_cmd", mock_proc)
        res = await bg_task.send_input("hello stdin")
        self.assertIn("OK: input sent to task_3", res)
        mock_stdin.write.assert_called_once_with(b"hello stdin\n")



class TestKillAllBackgroundTasks(unittest.TestCase):
    def test_kills_each_task_sync(self):
        t1 = BackgroundTask("t1", "cmd", MagicMock())
        t1.kill_sync = MagicMock()
        t2 = BackgroundTask("t2", "cmd", MagicMock())
        t2.kill_sync = MagicMock()

        kill_all_background_tasks([t1, t2])

        t1.kill_sync.assert_called_once()
        t2.kill_sync.assert_called_once()

    def test_skips_tasks_without_kill(self):
        plain = object()
        # Should not raise on arbitrary objects
        kill_all_background_tasks([plain])

    def test_read_task_cancelled(self):
        t = BackgroundTask("t3", "cmd", MagicMock())
        t.kill_sync = MagicMock()
        t.read_task = MagicMock()
        t.read_task.done.return_value = False

        kill_all_background_tasks([t])

        t.read_task.cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
