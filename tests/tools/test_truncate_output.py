import os
import unittest

from core.config import LAST_TOOL_LOG_FILE
from tools.base import truncate_output


class TestTruncateOutput(unittest.TestCase):
    def test_truncate_output_saves_log(self):
        large_text = "A" * 5000
        res = truncate_output(large_text, max_chars=1000)

        log_path = LAST_TOOL_LOG_FILE
        self.assertTrue(os.path.exists(log_path))
        self.assertIn("Full output saved to", res)
        self.assertIn("Use read tool or shell (grep/head/tail) to inspect", res)

        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, large_text)

    def test_truncate_output_unique_log_per_tool(self):
        text1 = "TOOL_1_" + ("A" * 2000)
        text2 = "TOOL_2_" + ("B" * 2000)

        res1 = truncate_output(text1, max_chars=100, tool_name="shell", tool_id="call_1")
        res2 = truncate_output(text2, max_chars=100, tool_name="shell", tool_id="call_2")

        self.assertIn("shell_call_1.log", res1)
        self.assertIn("shell_call_2.log", res2)

        path1 = [line for line in res1.split() if "shell_call_1.log" in line][0].rstrip(".")
        path2 = [line for line in res2.split() if "shell_call_2.log" in line][0].rstrip(".")

        self.assertTrue(os.path.exists(path1))
        self.assertTrue(os.path.exists(path2))

        with open(path1, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), text1)

        with open(path2, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), text2)

