import unittest
from unittest.mock import MagicMock

from core.background_task import BackgroundTask, process_carriage_returns, strip_ansi


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
        self.assertIn("stdin is not writable", res)

    async def test_send_input_via_master_fd(self):
        t = BackgroundTask("t5", "cmd", None)
        t.is_running = True
        # We can't really write to an fd in a unit test, but we can test the
        # branch logic by using a valid pipe write end
        import os
        r_fd, w_fd = os.pipe()
        try:
            t.master_fd = w_fd
            res = await t.send_input("test input")
            self.assertIn("Input sent to task t5", res)
            # Verify the data was written
            data = os.read(r_fd, 1024)
            self.assertEqual(data, b"test input\n")
        finally:
            os.close(r_fd)
            os.close(w_fd)


if __name__ == "__main__":
    unittest.main()
