import os
import unittest

from tools.base import truncate_output


class TestTruncateOutput(unittest.TestCase):
    def test_truncate_output_saves_log(self):
        large_text = "A" * 5000
        res = truncate_output(large_text, max_chars=1000)

        self.assertIn("Full output saved to", res)
        self.assertIn("Use read tool or shell (grep/head/tail) to inspect", res)
        log_path = [word for word in res.split() if word.endswith(".log") or ".log." in word or ".log]" in word][0].rstrip(".").rstrip("]")
        self.assertTrue(os.path.exists(log_path))

        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, large_text)

    def test_truncate_output_start_line_hint(self):
        multi_line_text = "\n".join([f"Line {i}" for i in range(1, 200)])
        res = truncate_output(multi_line_text, max_chars=100)
        self.assertIn("lines 1-", res)
        self.assertIn("Use read tool (start_line=", res)

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

    def test_truncate_output_from_end(self):
        text = "HEAD_" + ("X" * 1000) + "_TAIL"
        res = truncate_output(text, max_chars=100, from_end=True, save_log=False)
        self.assertTrue(res.startswith("[Output truncated. Showing last 100 chars."))
        self.assertTrue(res.endswith("_TAIL"))
        self.assertNotIn("HEAD_", res)

    def test_truncate_output_json_pretty_formatting(self):
        import json
        large_json_dict = {"status": "success", "data": ["item_" + str(i) for i in range(500)]}
        single_line_json = json.dumps(large_json_dict)
        self.assertNotIn("\n", single_line_json)

        res = truncate_output(single_line_json, max_chars=100, tool_name="mcp_test", tool_id="json_1")
        self.assertIn("Format: JSON.", res)
        self.assertIn("inspect formatted JSON log", res)

        log_path = [line for line in res.split() if "mcp_test_json_1.log" in line][0].rstrip(".")
        with open(log_path, "r", encoding="utf-8") as f:
            log_content = f.read()

        # Verify saved log was pretty-printed into multiple lines
        self.assertIn("\n", log_content)
        self.assertEqual(json.loads(log_content), large_json_dict)

    def test_format_line_pagination_single_line_error_hint(self):
        from tools.utils import format_line_pagination
        res = format_line_pagination(["single line content"], start_line=140, path="test.log")
        self.assertIn("ERR: start_line (140) exceeds total file line count (1)", res)
        self.assertIn("File has only 1 total line", res)
        self.assertIn("content_offset", res)


