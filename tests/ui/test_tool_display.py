import unittest

from core.tool_display import extract_tool_display


class TestToolDisplay(unittest.TestCase):
    def test_shell_command(self):
        self.assertEqual(extract_tool_display("shell", {"command": "ls -la"}), "ls -la")

    def test_read_path(self):
        self.assertEqual(extract_tool_display("read", {"path": "x.py"}), "x.py")

    def test_path_formatting_relative_and_absolute(self):
        import os

        root = os.path.realpath("/app/project")
        in_path = os.path.join(root, "src", "main.py")
        self.assertEqual(extract_tool_display("create", {"TargetFile": in_path}, cwd=root), in_path)

        out_path = os.path.realpath("/tmp/other/file.py")
        self.assertEqual(extract_tool_display("create", {"TargetFile": out_path}, cwd=root), out_path)

    def test_ask_user_questions(self):
        res = extract_tool_display("ask_user", {"questions": [{"question_text": "Which framework?"}]})
        self.assertEqual(res, '"Which framework?"')

    def test_subagent_description(self):
        res = extract_tool_display("subagent", {"description": "find bugs", "prompt": "long prompt"})
        self.assertEqual(res, '"find bugs"')
        res2 = extract_tool_display("invoke_subagent", {"description": "find bugs", "prompt": "long prompt"})
        self.assertEqual(res2, '"find bugs"')

    def test_manage_shell_action_and_id(self):
        res = extract_tool_display("manage_shell", {"action": "status", "task_id": "shell_123"})
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
                "ReplacementContent": "<a>Get Started</a>",
            },
        )
        self.assertEqual(res, "/path/to/index.html")

    def test_image_read_not_expandable(self):
        from widgets.chat_view import ToolCallWidget

        # Image file target
        w1 = ToolCallWidget("read", "/path/to/123.png", args={"path": "/path/to/123.png"})
        self.assertFalse(w1.is_expandable())

        # Text file target
        w2 = ToolCallWidget("read", "/path/to/main.py", args={"path": "/path/to/main.py"})
        self.assertFalse(w2.is_expandable())

    def test_create_tool_widget_render_diff_vs_clean_code(self):
        from widgets.chat_view import ToolCallWidget

        # Create with diff (file update)
        w_diff = ToolCallWidget(
            "create",
            "foo.py",
            args={"path": "foo.py", "content": "def bar(): pass"},
            result_text="OK: file 'foo.py' updated.\n\n--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,1 @@\n-def foo(): pass\n+def bar(): pass\n[Linter Feedback]: F821 undefined name",
        )
        w_diff.is_expanded = True
        w_diff.render_content()

        # Create without diff (new file)
        w_new = ToolCallWidget(
            "create",
            "foo.py",
            args={"path": "foo.py", "content": "print('hello')"},
            result_text="OK: file 'foo.py' created.\n[Hint: extra hint]",
        )
        w_new.is_expanded = True
        w_new.render_content()

    def test_edit_tool_cleaning_system_noise(self):
        from widgets.chat_view import ToolCallWidget

        widget = ToolCallWidget(
            "edit",
            "code.py",
            args={"target_file": "code.py", "target_content": "a", "replacement_content": "b"},
            result_text="OK: file 'code.py' updated.\n\n--- a/code.py\n+++ b/code.py\n@@ -1,1 +1,1 @@\n-a\n+b\n[Linter Feedback]: F841 unused variable\n[Hint: Some system hint]",
        )
        diff_renderable = widget._format_edit_diff(widget.result_text, "code.py")
        formatted_text = "\n".join(t.plain for t in diff_renderable.formatted_lines)
        self.assertNotIn("OK: file", formatted_text)
        self.assertNotIn("[Linter Feedback]", formatted_text)
        self.assertNotIn("[Hint:", formatted_text)

    def test_format_edit_diff_monotonic_line_numbers(self):
        from widgets.chat_diff import format_edit_diff

        diff_text = (
            "--- a/main.py\n"
            "+++ b/main.py\n"
            "@@ -10,3 +10,4 @@\n"
            " line10\n"
            "-line11\n"
            "+line11_new\n"
            "+line12_new\n"
            " line13\n"
        )
        r = format_edit_diff(diff_text, "main.py")
        lines = [t.plain for t in r.formatted_lines]
        # Line numbers for context, delete, insert should be monotonic (10, 11-, 11+, 12+, 13)
        num_strs = [l.split()[0] for l in lines]
        self.assertEqual(num_strs, ["10", "11", "11", "12", "13"])

    def test_shell_cleaning_system_noise(self):
        from widgets.chat_view import ToolCallWidget

        widget = ToolCallWidget("shell", "echo test", args={"command": "echo test"})
        cleaned = widget._clean_bash_output(
            "Command is running in the background [Background Task ID: task-1]\nYou will be notified automatically\nreal output"
        )
        self.assertEqual(cleaned, "real output")


    def test_format_edit_diff_unspaced_context_lines(self):
        from widgets.chat_diff import format_edit_diff

        diff_text = (
            "--- a/prompts.py\n"
            "+++ b/prompts.py\n"
            "@@ -27,7 +27,7 @@\n"
            "## Core Rules\n"
            "1. Autonomous Operation: You have no UI interaction with the user.\n"
            "-2. Relative Paths: Always use relative file paths.\n"
            "+2. Relative Paths: Use relative paths.\n"
            "3. Research First: Read and inspect relevant files.\n"
        )
        res = format_edit_diff(diff_text, "prompts.py")
        plain_lines = [line_item.plain for line_item in res.formatted_lines]
        # Verify line 29 (-) and line 29 (+) match the modified line symbol
        self.assertTrue(any("29 -" in line_item for line_item in plain_lines))
        self.assertTrue(any("29 +" in line_item for line_item in plain_lines))


if __name__ == "__main__":
    unittest.main()

