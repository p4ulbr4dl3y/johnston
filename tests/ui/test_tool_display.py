import unittest

from core.tool_display import extract_tool_display


class TestToolDisplay(unittest.TestCase):
    def test_shell_command(self):
        self.assertEqual(extract_tool_display("shell", {"command": "ls -la"}), "ls -la")

    def test_read_path(self):
        self.assertEqual(extract_tool_display("read", {"path": "/tmp/x.py"}), "/tmp/x.py")

    def test_ask_user_questions(self):
        res = extract_tool_display("ask_user", {"questions": [{"question_text": "Which framework?"}]})
        self.assertEqual(res, '"Which framework?"')

    def test_subagent_description(self):
        res = extract_tool_display("subagent", {"description": "find bugs", "prompt": "long prompt"})
        self.assertEqual(res, '"find bugs"')
        res2 = extract_tool_display("invoke_subagent", {"description": "find bugs", "prompt": "long prompt"})
        self.assertEqual(res2, '"find bugs"')

    def test_manage_task_action_and_id(self):
        res = extract_tool_display("manage_task", {"action": "status", "task_id": "shell_123"})
        self.assertEqual(res, "status shell_123")



    def test_get_mcp_schema_tool_target(self):
        res = extract_tool_display("get_mcp_schema", {"server": "colab", "tool": "search"})
        self.assertEqual(res, "search")

    def test_unknown_tool_fallback(self):
        self.assertEqual(extract_tool_display("unknown_tool", {}), "unknown_tool")

    def test_long_target_is_truncated(self):
        long_cmd = "echo " + "a" * 200
        res = extract_tool_display("shell", {"command": long_cmd})
        self.assertLessEqual(len(res), 60)
        self.assertIn("...", res)

    def test_case_insensitive_name(self):
        # Capitalized tool names (which OpenAI never sends, but we guard) normalize
        self.assertEqual(extract_tool_display("Shell", {"command": "pwd"}), "pwd")

    def test_replace_file_content_target_file(self):
        res = extract_tool_display(
            "replace_file_content",
            {
                "TargetFile": "/path/to/index.html",
                "Instruction": "replace button",
                "ReplacementContent": "<a>Get Started</a>"
            }
        )
        self.assertEqual(res, "/path/to/index.html")

    def test_image_read_not_expandable(self):
        from widgets.chat_view import ToolCallWidget
        # Image file target
        w1 = ToolCallWidget("read", "/path/to/123.png", args={"path": "/path/to/123.png"})
        self.assertFalse(w1.is_expandable())

        # Text file target
        w2 = ToolCallWidget("read", "/path/to/main.py", args={"path": "/path/to/main.py"})
        self.assertTrue(w2.is_expandable())

        # Image result text
        w3 = ToolCallWidget("read", "file", result_text="[Image file: '123.png' (100x100 px, format: JPEG)]")
        self.assertFalse(w3.is_expandable())


if __name__ == "__main__":
    unittest.main()
