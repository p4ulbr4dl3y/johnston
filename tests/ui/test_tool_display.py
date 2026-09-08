import os
import sys
import unittest

import pytest

from widgets.presentation.tool_display import extract_tool_display


class TestToolDisplay(unittest.TestCase):
    def test_shell_command(self):
        self.assertEqual(extract_tool_display("shell", {"command": "ls -la"}), "ls -la")

    def test_read_path(self):
        self.assertEqual(extract_tool_display("read", {"path": "x.py"}), "x.py")
        self.assertEqual(extract_tool_display("read", {"path": "x.py", "start_line": 10, "end_line": 50}), "x.py:10-50")
        self.assertEqual(extract_tool_display("read", {"path": "x.py", "start_line": 42, "end_line": 42}), "x.py:42")
        self.assertEqual(extract_tool_display("read", {"path": "x.py", "start_line": 100}), "x.py:100+")
        self.assertEqual(extract_tool_display("read", {"path": "x.py", "end_line": 80}), "x.py:1-80")
        self.assertEqual(extract_tool_display("read", {"path": "x.py", "content_offset": 512}), "x.py:+512B")
        self.assertEqual(extract_tool_display("read", {"path": "x.py", "content_offset": 4096}), "x.py:+4KB")
        self.assertEqual(extract_tool_display("read", {"path": "x.py", "content_offset": 1572864}), "x.py:+1.5MB")

    @pytest.mark.skipif(sys.platform == "win32", reason="expects POSIX-style separators")
    def test_path_formatting_relative_and_absolute(self):
        import os

        root = os.path.realpath("/app/project")
        in_path = os.path.join(root, "src", "main.py")
        self.assertEqual(extract_tool_display("create", {"path": in_path}), in_path)

        out_path = os.path.realpath("/tmp/other/file.py")
        self.assertEqual(extract_tool_display("create", {"path": out_path}), out_path)

    def test_ask_user_questions(self):
        res = extract_tool_display("ask_user", {"questions": [{"question": "Which framework?"}]})
        self.assertEqual(res, '"Which framework?"')

    def test_subagent_title(self):
        res = extract_tool_display("invoke_subagent", {"title": "find bugs", "prompt": "long prompt"})
        self.assertEqual(res, 'Worker: "find bugs"')
        res2 = extract_tool_display("invoke_subagent", {"title": "find bugs", "type": "worker"})
        self.assertEqual(res2, 'Worker: "find bugs"')
        res3 = extract_tool_display("invoke_subagent", {"title": "find bugs", "type": "explorer"})
        self.assertEqual(res3, 'Explorer: "find bugs"')
        res4 = extract_tool_display("invoke_subagent", {"title": "find bugs", "role": "reviewer"})
        self.assertEqual(res4, 'Reviewer: "find bugs"')

    def test_subagent_prompt_only_empty_parens(self):
        # No title -> shows Worker
        self.assertEqual(extract_tool_display("invoke_subagent", {"prompt": "long prompt"}), "Worker")

    def test_kill_display(self):
        res = extract_tool_display("kill", {"id": "task_123"})
        self.assertEqual(res, "task_123")

    def test_message_subagent_display(self):
        res = extract_tool_display("message_subagent", {"id": "sub_123", "message": "hello"})
        self.assertEqual(res, 'to sub_123: "hello"')

    def test_unknown_tool_compact_dict(self):
        # Non-builtin (MCP/custom) tools always render the compact dict format.
        self.assertEqual(extract_tool_display("unknown_tool", {}), "")
        self.assertEqual(extract_tool_display("unknown_tool", {"query": "x"}), '{query: "x"}')

    def test_builtin_missing_arg_empty_parens(self):
        for name in ("read", "create", "edit", "shell", "web_fetch", "update_plan"):
            self.assertEqual(extract_tool_display(name, {}), "")
        self.assertEqual(extract_tool_display("ask_user", {}), "")
        self.assertEqual(extract_tool_display("invoke_subagent", {}), "Worker")
        self.assertEqual(extract_tool_display("kill", {}), "")
        self.assertEqual(extract_tool_display("message_subagent", {}), "")

    def test_builtin_no_generic_string_fallback(self):
        # edit without path, only old/new strings -> empty parens, not old_str.
        self.assertEqual(extract_tool_display("edit", {"old_str": "a", "new_str": "b"}), "")
        # update_plan without a plan list -> empty parens (explanation ignored).
        self.assertEqual(extract_tool_display("update_plan", {"explanation": "why"}), "")
        # shell with only timeout -> empty parens.
        self.assertEqual(extract_tool_display("shell", {"timeout": 30}), "")

    def test_update_plan_counter(self):
        self.assertEqual(
            extract_tool_display(
                "update_plan", {"explanation": "phase one", "plan": [{"status": "completed"}, {"status": "pending"}]}
            ),
            "1/2 done",
        )
        self.assertEqual(
            extract_tool_display(
                "update_plan",
                {
                    "plan": [
                        {"step": "Setup DB", "status": "completed"},
                        {"step": "Write tests", "status": "in_progress"},
                    ]
                },
            ),
            "1/2: Write tests",
        )
        self.assertEqual(
            extract_tool_display(
                "update_plan",
                {
                    "plan": [
                        {"step": "Setup DB", "status": "pending"},
                        {"step": "Write tests", "status": "pending"},
                    ]
                },
            ),
            "0/2: Setup DB",
        )
        self.assertEqual(
            extract_tool_display(
                "update_plan",
                {
                    "plan": [
                        {"step": "Setup DB", "status": "completed"},
                        {"step": "Write tests", "status": "completed"},
                    ]
                },
            ),
            "2/2 done",
        )
        self.assertEqual(extract_tool_display("update_plan", {"explanation": "phase one"}), "")

    def test_long_target_is_truncated(self):
        long_cmd = "echo " + "a" * 200
        res = extract_tool_display("shell", {"command": long_cmd})
        self.assertLessEqual(len(res), 60)
        self.assertIn("...", res)

    def test_case_insensitive_name(self):
        # Capitalized tool names (which OpenAI never sends, but we guard) normalize
        self.assertEqual(extract_tool_display("Shell", {"command": "pwd"}), "pwd")

    def test_edit_target_file(self):
        res = extract_tool_display(
            "edit",
            {
                "path": "/path/to/index.html",
                "old_str": "replace button",
                "new_str": "<a>Get Started</a>",
            },
        )
        self.assertEqual(res, "/path/to/index.html")

    def test_image_read_not_expandable(self):
        from widgets.chat_toolcall import ToolCallWidget

        # Image file target
        w1 = ToolCallWidget("read", "/path/to/123.png", args={"path": "/path/to/123.png"})
        self.assertFalse(w1.is_expandable())

        # Text file target
        w2 = ToolCallWidget("read", "/path/to/main.py", args={"path": "/path/to/main.py"})
        self.assertFalse(w2.is_expandable())

    def test_create_tool_widget_render_diff_vs_clean_code(self):
        from widgets.chat_toolcall import ToolCallWidget

        # Create with diff (file update)
        w_diff = ToolCallWidget(
            "create",
            "foo.py",
            args={"path": "foo.py", "content": "def bar(): pass"},
            result_text="OK: file 'foo.py' updated.\n\n--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,1 @@\n-def foo(): pass\n+def bar(): pass\n",
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
        from widgets.chat_toolcall import ToolCallWidget

        widget = ToolCallWidget(
            "edit",
            "code.py",
            args={"path": "code.py"},
            result_text="OK: file 'code.py' updated.\n\n--- a/code.py\n+++ b/code.py\n@@ -1,1 +1,1 @@\n-a\n+b\n",
        )
        diff_renderable = widget._format_edit_diff(widget.result_text, "code.py")
        formatted_text = "\n".join(t.plain for t in diff_renderable.formatted_lines)
        self.assertNotIn("OK: file", formatted_text)
        self.assertIn("b", formatted_text)

    def test_format_edit_diff_monotonic_line_numbers(self):
        from widgets.presentation.widgets.chat_diff import format_edit_diff

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
        num_strs = [line.split()[0] for line in lines]
        self.assertEqual(num_strs, ["10", "11", "11", "12", "13"])

    def test_shell_cleaning_system_noise(self):
        from widgets.chat_toolcall import ToolCallWidget

        widget = ToolCallWidget("shell", "echo test", args={"command": "echo test"})
        cleaned = widget._clean_bash_output(
            "real output\n... [Output truncated: showing last 100 chars (lines 1-10 of 10). Full log: /tmp/log. Use read to inspect.]"
        )
        self.assertIn("real output", cleaned)
        self.assertIn("Log: /tmp/log", cleaned)


    def test_format_edit_diff_unspaced_context_lines(self):
        from widgets.presentation.widgets.chat_diff import format_edit_diff

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

    def test_shorten_path_rules(self):
        import os

        from widgets.presentation.tool_display import shorten_path, split_path_suffix

        # Suffix splitting
        self.assertEqual(split_path_suffix("foo.py:10-20"), ("foo.py", ":10-20"))
        self.assertEqual(split_path_suffix("foo.py:+512B"), ("foo.py", ":+512B"))
        self.assertEqual(split_path_suffix("foo.py:42:15"), ("foo.py", ":42:15"))
        self.assertEqual(split_path_suffix("foo.py"), ("foo.py", ""))
        self.assertEqual(split_path_suffix(None), ("", ""))
        self.assertEqual(split_path_suffix(123), ("", ""))

        home = os.path.abspath(os.path.expanduser("~"))
        cwd = os.path.abspath(os.getcwd())

        # Inside CWD
        in_cwd = os.path.join(cwd, "src", "code.py")
        self.assertEqual(shorten_path(in_cwd), "src/code.py")
        self.assertEqual(shorten_path(f"{in_cwd}:10-20"), "src/code.py:10-20")

        # Double-dot prefix filename inside CWD (e.g. ..env) must NOT be rejected
        dotdot_file = os.path.join(cwd, "..env")
        self.assertEqual(shorten_path(dotdot_file), "..env")

        # Leading ./ or .\ and pure ./
        self.assertEqual(shorten_path("./src/code.py"), "src/code.py")
        self.assertEqual(shorten_path(".\\src\\code.py"), "src/code.py")
        self.assertEqual(shorten_path("./"), ".")
        self.assertEqual(shorten_path(".\\"), ".")

        # Windows-style backslashes normalized
        self.assertEqual(shorten_path("src\\sub\\code.py"), "src/sub/code.py")

        # In HOME but outside CWD (if possible)
        outside_cwd = os.path.join(home, ".johnston", "config.toml")
        if not outside_cwd.startswith(cwd):
            self.assertEqual(shorten_path(outside_cwd), "~/.johnston/config.toml")
            self.assertEqual(shorten_path(f"{outside_cwd}:42"), "~/.johnston/config.toml:42")

        # Explicit CWD argument test
        fake_cwd = os.path.abspath("/custom/project")
        self.assertEqual(shorten_path("/custom/project/a/b.py", cwd=fake_cwd), "a/b.py")

        # Empty / non-string
        self.assertEqual(shorten_path(""), "")
        self.assertEqual(shorten_path(None), "")

    def test_extract_tool_display_shortens_paths(self):
        import os

        cwd = os.path.abspath(os.getcwd())
        in_cwd = os.path.join(cwd, "tests", "test_foo.py")

        # Read
        self.assertEqual(extract_tool_display("read", {"path": in_cwd, "start_line": 5}), "tests/test_foo.py:5+")
        # Create
        self.assertEqual(extract_tool_display("create", {"path": in_cwd}), "tests/test_foo.py")
        # Edit
        self.assertEqual(extract_tool_display("edit", {"path": in_cwd}), "tests/test_foo.py")
        # Search
        self.assertEqual(extract_tool_display("search", {"query": "fn", "path": in_cwd}), '"fn" in tests/test_foo.py')
        self.assertEqual(extract_tool_display("search", {"query": "fn", "path": cwd}), '"fn"')
        self.assertEqual(extract_tool_display("search", {"query": "fn", "path": "./"}), '"fn"')

        home = os.path.abspath(os.path.expanduser("~"))
        in_home = os.path.join(home, ".test_cfg.json")
        if not in_home.startswith(cwd):
            self.assertEqual(extract_tool_display("read", {"path": in_home}), "~/.test_cfg.json")

    def test_read_file_content_with_tilde_and_limit(self):
        import tempfile

        from widgets.utils.file_reader import read_file_content

        self.assertIsNone(read_file_content(""))
        self.assertIsNone(read_file_content(None))
        self.assertIsNone(read_file_content("/non/existent/path/for/sure.txt"))

        with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False) as f:
            f.write("a" * 100)
            f.flush()
            temp_name = f.name

        try:
            self.assertEqual(read_file_content(temp_name, max_bytes=10), "a" * 10)
        finally:
            os.remove(temp_name)

    def test_build_synthetic_create_diff_clean_header(self):
        from widgets.presentation.tool_renderers import build_synthetic_create_diff

        diff = build_synthetic_create_diff("/var/log/syslog", "line 1")
        self.assertNotIn("a//var", diff)
        self.assertIn("--- a/var/log/syslog", diff)


if __name__ == "__main__":
    unittest.main()

