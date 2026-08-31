import os
import unittest

from tools.base import truncate_output


class TestTruncateOutput(unittest.TestCase):
    def test_truncate_output_saves_log(self):
        large_text = "A" * 5000
        res = truncate_output(large_text, max_chars=1000)

        self.assertIn("log ", res)
        self.assertIn("next read(path=", res)
        log_path = (
            [word for word in res.split() if word.endswith(".log") or ".log." in word or ".log]" in word or ".log|" in word or word.endswith(".log'")][0]
            .rstrip(".")
            .rstrip("]")
            .rstrip("'")
        )
        self.assertTrue(os.path.exists(log_path))

        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, large_text)

    def test_truncate_output_start_line_hint(self):
        multi_line_text = "\n".join([f"Line {i}" for i in range(1, 200)])
        res = truncate_output(multi_line_text, max_chars=100)
        self.assertIn("lines 1..", res)
        self.assertIn("next read(path=", res)
        self.assertIn("start_line=", res)

    def test_truncate_output_unique_log_per_tool(self):
        text1 = "TOOL_1_" + ("A" * 2000)
        text2 = "TOOL_2_" + ("B" * 2000)

        res1 = truncate_output(text1, max_chars=100, tool_name="shell")
        res2 = truncate_output(text2, max_chars=100, tool_name="shell")

        path1 = [word for word in res1.split() if ".log" in word][0].rstrip(".").rstrip("'")
        path2 = [word for word in res2.split() if ".log" in word][0].rstrip(".").rstrip("'")

        # Same tool name, different snapshots -> distinct unique files.
        self.assertNotEqual(path1, path2)
        self.assertTrue(os.path.basename(path1).startswith("shell-"))
        self.assertTrue(os.path.exists(path1))
        self.assertTrue(os.path.exists(path2))

        with open(path1, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), text1)

        with open(path2, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), text2)

    def test_truncate_output_from_end(self):
        text = "HEAD_\n" + ("X\n" * 100) + "_TAIL"
        res = truncate_output(text, max_chars=50, from_end=True, save_log=False)
        self.assertIn("last 50 chars", res)
        self.assertIn("lines ", res)
        self.assertTrue(res.endswith("_TAIL"))
        self.assertNotIn("HEAD_", res)

    def test_truncate_output_json_pretty_formatting(self):
        import json

        large_json_dict = {"status": "success", "data": ["item_" + str(i) for i in range(500)]}
        single_line_json = json.dumps(large_json_dict)
        self.assertNotIn("\n", single_line_json)

        res = truncate_output(single_line_json, max_chars=100, tool_name="mcp_test")
        self.assertIn("log ", res)
        self.assertIn(".json", res)

        log_path = [word for word in res.split() if ".json" in word][0].rstrip(".").rstrip("'")
        with open(log_path, "r", encoding="utf-8") as f:
            log_content = f.read()

        # Verify saved file was pretty-printed into multiple lines and has .json extension
        self.assertIn("\n", log_content)
        self.assertTrue(log_path.endswith(".json"))
        self.assertEqual(json.loads(log_content), large_json_dict)

    def test_truncate_output_custom_extension(self):
        text = "# Markdown Title\n" + ("content " * 500)
        res = truncate_output(text, max_chars=50, tool_name="web_fetch", ext=".md")
        self.assertIn(".md", res)
        path = [word for word in res.split() if ".md" in word][0].rstrip(".")
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith(".md"))
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), text)

    def test_truncate_output_default_uses_configured_cap(self):
        import unittest.mock as mock

        from core.infrastructure.config.settings import JohnstonSettings, ToolsSettings

        # Regression: with no explicit max_chars, truncate_output must honor the
        # configurable tools.max_tool_output_chars from config.json.
        cfg = JohnstonSettings(tools=ToolsSettings(max_tool_output_chars=10))
        with mock.patch("core.infrastructure.config.settings.get_settings", return_value=cfg):
            res = truncate_output("X" * 100, tool_name="cap")
        self.assertIn("log ", res)

    def test_truncate_output_clips_log_at_max_size(self):
        import unittest.mock as mock

        from core.infrastructure.config.settings import JohnstonSettings, ToolsSettings

        cfg = JohnstonSettings(tools=ToolsSettings(max_snapshot_log_bytes=1000))
        with mock.patch("core.infrastructure.config.settings.get_settings", return_value=cfg):
            res = truncate_output("X" * 5000, max_chars=100, tool_name="clip")
        log_path = [word for word in res.split() if ".log" in word][0].rstrip(".")

        with open(log_path, "r", encoding="utf-8") as f:
            log_content = f.read()

        self.assertIn("snapshot clipped | max size", log_content)
        self.assertTrue(len(log_content) <= 1000 + len("\n... [snapshot clipped | max size]\n"))

    def test_truncate_output_mcp_name_has_no_duplicate_prefix(self):
        res = truncate_output("M" * 5000, max_chars=100, tool_name="mcp_huge_tool")
        log_path = [word for word in res.split() if ".log" in word][0].rstrip(".")
        base = os.path.basename(log_path)

        self.assertTrue(base.startswith("mcp_huge_tool-"), base)
        self.assertNotIn("mcp_mcp_", base)

    def test_truncate_output_long_tool_name_capped(self):
        res = truncate_output("L" * 5000, max_chars=100, tool_name="very_long_tool_name_" * 5)
        log_path = [word for word in res.split() if ".log" in word][0].rstrip(".")
        base = os.path.basename(log_path)

        # Prefix capped at 40 chars + "-" + 4 hex + ".log"
        self.assertTrue(len(base) <= 40 + 1 + 4 + 4, base)

    def test_format_line_pagination_single_line_error_hint(self):
        from tools.utils import format_line_pagination

        res = format_line_pagination(["single line content"], start_line=140, path="test.log")
        self.assertIn("ERR: range 'read': start_line (140) exceeds line count (1)", res.display)
        self.assertIn("File has 1 line", res.display)
        self.assertIn("content_offset", res.display)

    def test_truncate_output_with_explicit_log_path(self):
        text = "LINE1\n" + ("LINE\n" * 50) + "LINE52"
        # from_end=True with explicit log_path and save_log=False
        res_end = truncate_output(
            text,
            max_chars=30,
            from_end=True,
            save_log=False,
            log_path="/path/to/custom.log",
        )
        self.assertIn("log /path/to/custom.log", res_end)
        self.assertIn("last 30 chars", res_end)

        # from_end=False with explicit log_path and save_log=False
        res_lead = truncate_output(
            text,
            max_chars=30,
            from_end=False,
            save_log=False,
            log_path="/path/to/custom.log",
        )
        self.assertIn("log /path/to/custom.log", res_lead)
        self.assertIn("next read(path='/path/to/custom.log'", res_lead)
