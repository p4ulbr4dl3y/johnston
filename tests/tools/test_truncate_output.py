import os
import unittest

from tools.base import truncate_output


class TestTruncateOutput(unittest.TestCase):
    def test_truncate_output_saves_log(self):
        large_text = "A" * 5000
        res = truncate_output(large_text, max_chars=1000)

        log_path = os.path.expanduser("~/.johnston/logs/last_tool.log")
        self.assertTrue(os.path.exists(log_path))
        self.assertIn("Full output saved to", res)
        self.assertIn("Use read tool to inspect", res)

        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, large_text)
