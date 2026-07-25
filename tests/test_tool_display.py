import unittest

from core.tool_display import extract_tool_display


class TestToolDisplay(unittest.TestCase):
    def test_bash_command(self):
        self.assertEqual(extract_tool_display("bash", {"command": "ls -la"}), "ls -la")

    def test_read_path(self):
        self.assertEqual(extract_tool_display("read", {"path": "/tmp/x.py"}), "/tmp/x.py")

    def test_ask_user_questions(self):
        res = extract_tool_display("ask_user", {"questions": [{"question_text": "Which framework?"}]})
        self.assertEqual(res, '"Which framework?"')

    def test_subagent_description(self):
        res = extract_tool_display("subagent", {"description": "find bugs", "prompt": "long prompt"})
        self.assertEqual(res, '"find bugs"')

    def test_manage_task_action_and_id(self):
        res = extract_tool_display("manage_task", {"action": "status", "task_id": "bash_123"})
        self.assertEqual(res, "status bash_123")

    def test_view_image_basename(self):
        res = extract_tool_display("view_image", {"path": "/tmp/img.png"})
        self.assertEqual(res, "img.png")

    def test_unknown_tool_fallback(self):
        self.assertEqual(extract_tool_display("unknown_tool", {}), "unknown_tool")

    def test_long_target_is_truncated(self):
        long_cmd = "echo " + "a" * 200
        res = extract_tool_display("bash", {"command": long_cmd})
        self.assertLessEqual(len(res), 60)
        self.assertIn("...", res)

    def test_case_insensitive_name(self):
        # Capitalized tool names (which OpenAI never sends, but we guard) normalize
        self.assertEqual(extract_tool_display("Bash", {"command": "pwd"}), "pwd")


if __name__ == "__main__":
    unittest.main()
