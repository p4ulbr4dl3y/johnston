import os
import tempfile
import unittest
from unittest.mock import MagicMock

from rich.console import Console
from rich.text import Text
from textual._context import active_app

from widgets.chat_toolcall import ToolCallWidget
from widgets.presentation.widgets.chat_diff import DiffRenderable


class TestToolExpansion(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = self.temp_dir.name
        self.mock_app = MagicMock()
        self.mock_app.console = Console()
        self.token = active_app.set(self.mock_app)

    def tearDown(self):
        self.temp_dir.cleanup()
        active_app.reset(self.token)

    def test_tool_call_widget_init(self):
        widget = ToolCallWidget(
            tool_type="create",
            target="test.txt",
            result_text="Success",
            args={"path": "test.txt", "content": "hello\nworld"},
        )
        widget.render_header()
        self.assertFalse(widget.is_expanded)
        self.assertEqual(widget.tool_type, "create")
        self.assertEqual(widget.args["content"], "hello\nworld")
        self.assertIn("●", str(widget.header_label.render()))

    def test_tool_call_widget_toggle_expand_syntax(self):
        widget = ToolCallWidget(
            tool_type="create", target="test.py", args={"path": "test.py", "content": "def foo():\n    return 42"}
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        self.assertIn("●", str(widget.header_label.render()))
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, DiffRenderable)
        self.assertIn("def foo():", content._text.plain)

        widget.toggle_expanded()
        self.assertFalse(widget.is_expanded)

    def test_edit_tool_toggle_expand_diff(self):
        diff_text = (
            "--- a/test.py\n"
            "+++ b/test.py\n"
            "@@ -7,1 +9,2 @@\n"
            "-def multiply(a, b):\n"
            "+def multiply(a: float, b: float) -> float:\n"
            "+    return a * b\n"
        )
        widget = ToolCallWidget(
            tool_type="edit",
            target="test.py",
            result_text=diff_text,
            args={
                "path": "test.py",
                "old_str": "def multiply(a, b):",
                "new_str": "def multiply(a: float, b: float) -> float:\n    return a * b",
            },
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, (Text, DiffRenderable))
        rendered_plain = content.plain
        self.assertNotIn("@@ -7,1 +9,2 @@", rendered_plain)
        self.assertIn("7 - def multiply(a, b):", rendered_plain)
        self.assertIn("9 + def multiply(a: float, b: float) -> float:", rendered_plain)
        self.assertIn("10 +     return a * b", rendered_plain)

    def test_edit_tool_handles_empty_context_lines(self):
        diff_text = (
            "@@ -327,5 +327,6 @@\n"
            " }, { threshold: 0.1 });\n"
            "\n"
            " document.querySelectorAll('.card-hover');\n"
            "+ // new comment\n"
            " </script>\n"
        )
        widget = ToolCallWidget(
            tool_type="edit", target="index.html", result_text=diff_text, args={"path": "index.html"}
        )
        widget.toggle_expanded()
        content = getattr(widget.content_widget, "_Static__content")
        rendered_plain = content.plain
        self.assertIn("327   }, { threshold: 0.1 });", rendered_plain)
        self.assertIn("328   ", rendered_plain)
        self.assertIn("329   document.querySelectorAll('.card-hover');", rendered_plain)
        self.assertIn("330 +  // new comment", rendered_plain)
        self.assertIn("331   </script>", rendered_plain)

    def test_diff_renderable_pads_background_lines(self):
        line = Text("85 + matched = 0")
        line.stylize("on #12261e")
        diff = DiffRenderable([line])

        mock_console = MagicMock()
        mock_console.render.side_effect = lambda line, opts: [line]
        options = MagicMock()
        options.max_width = 80
        options.update.return_value = options

        results = list(diff.__rich_console__(mock_console, options))
        self.assertEqual(len(results), 1)
        padded_line = results[0]
        self.assertEqual(len(padded_line.plain), 80)
        self.assertTrue(any(s.end == 80 and s.style == "on #12261e" for s in padded_line._spans))

    def test_edit_tool_error_display(self):
        error_text = "ERR: target not found in 'test.py' (10-20)."
        widget = ToolCallWidget(
            tool_type="edit",
            target="test.py",
            result_text=error_text,
            args={"path": "test.py", "old_str": "foo", "new_str": "bar"},
        )
        widget.set_result(error_text, status="error")
        self.assertEqual(widget.status, "error")
        # Error results are feedback for the agent, not user content — not expandable.
        self.assertFalse(widget.is_expandable())
        widget.toggle_expanded()
        self.assertFalse(widget.is_expanded)
        # Error text still renders if content is built directly.
        widget.render_content()
        content = getattr(widget.content_widget, "_Static__content")
        self.assertEqual(content, error_text)

    def test_hints_stripped_from_ui_display_but_retained_in_result_text(self):
        full_text = (
            "ERR: target not found.\n\n<hint file='test.py' line='15'>\nline 1\nline 2\n</hint>"
        )
        widget = ToolCallWidget(tool_type="edit", target="test.py", result_text=full_text, args={"path": "test.py"})
        widget.set_result(full_text, is_error=True)
        # result_text must keep <hint> for agent
        self.assertEqual(widget.result_text, full_text)
        # Error results for non-shell tools are not clickable/expandable in UI
        self.assertFalse(widget.is_clickable_header())

    def test_create_tool_error_display(self):
        error_text = "ERR: '/some/dir' is a directory"
        widget = ToolCallWidget(
            tool_type="create",
            target="/some/dir",
            result_text=error_text,
            args={"path": "/some/dir", "content": "some content"},
        )
        widget.set_result(error_text, status="error")
        self.assertEqual(widget.status, "error")
        # Error results are feedback for the agent, not user content — not expandable.
        self.assertFalse(widget.is_expandable())
        widget.toggle_expanded()
        self.assertFalse(widget.is_expanded)
        # Error text still renders if content is built directly.
        widget.render_content()
        content = getattr(widget.content_widget, "_Static__content")
        self.assertEqual(content, error_text)

    def test_update_plan_error_display(self):
        error_text = "ERR: 'plan' must be non-empty"
        widget = ToolCallWidget(tool_type="update_plan", target="plan", result_text=error_text, args={"plan": []})
        widget.set_result(error_text, status="error")
        self.assertEqual(widget.status, "error")
        # Error results are feedback for the agent, not user content — not expandable.
        self.assertFalse(widget.is_expandable())
        widget.toggle_expanded()
        self.assertFalse(widget.is_expanded)
        # Error text still renders if content is built directly.
        widget.render_content()
        content = getattr(widget.content_widget, "_Static__content")
        self.assertEqual(content, error_text)

    def test_edit_tool_html_embedded_javascript_lexing(self):
        diff_text = (
            "@@ -327,5 +327,10 @@\n"
            " }, { threshold: 0.1 });\n"
            " document.querySelectorAll('.card-hover');\n"
            "+ // CTA form handler\n"
            "+ function handleFormSubmit(e) {\n"
            "+   const form = document.getElementById('cta-form');\n"
            "+ }\n"
            " </script>\n"
            "</body>\n"
        )
        widget = ToolCallWidget(
            tool_type="edit", target="index.html", result_text=diff_text, args={"path": "index.html"}
        )
        widget.toggle_expanded()
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, (Text, DiffRenderable))
        # Check that tokens inside function handleFormSubmit have styles applied (not style=None)
        has_styled_spans = any(span.style is not None for span in content._spans)
        self.assertTrue(has_styled_spans)

        self.assertEqual(content.overflow, "fold")

    def test_edit_tool_html_tags_rendering(self):
        diff_text = (
            '@@ -274,5 +274,5 @@\n+ </button>\n+ </form>\n+ <p id="cta-success">\n+ Talk to Sales instead\n </div>\n'
        )
        widget = ToolCallWidget(
            tool_type="edit", target="index.html", result_text=diff_text, args={"path": "index.html"}
        )
        widget.toggle_expanded()
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, (Text, DiffRenderable))
        rendered_plain = content.plain
        self.assertIn("274 +  </button>", rendered_plain)
        self.assertIn("277 +  Talk to Sales instead", rendered_plain)

    def test_edit_tool_pascal_case_args_and_start_line(self):
        widget = ToolCallWidget(
            tool_type="edit",
            target="index.html",
            result_text="Successfully replaced content.",
            args={
                "path": "index.html",
                "old_str": "const form = document.getElementById('cta-form');",
                "new_str": "// CTA form handler\nconst form = document.getElementById('cta-form');",
                "start_line": 330,
            },
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, (Text, DiffRenderable))
        rendered_plain = content.plain
        self.assertIn("330 + // CTA form handler", rendered_plain)
        self.assertIn("331   const form = document.getElementById('cta-form');", rendered_plain)

    def test_edit_tool_replace(self):
        widget = ToolCallWidget(
            tool_type="edit",
            target="app.py",
            result_text="",
            args={
                "path": "app.py",
                "old_str": "x = 1",
                "new_str": "x = 10",
            },
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, (Text, DiffRenderable))
        rendered_plain = content.plain
        self.assertIn("1 - x = 1", rendered_plain)
        self.assertIn("1 + x = 10", rendered_plain)

    def test_shell_tool_append_output(self):
        widget = ToolCallWidget(tool_type="shell", target="echo 'live stream'", args={"command": "echo 'live stream'"})
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)

        widget.append_shell_output("line 1\n")
        widget.append_shell_output("line 2\n")

        content = getattr(widget.content_widget, "_Static__content")
        self.assertEqual(content, "line 1\nline 2")

    def test_read_tool_not_expandable(self):
        widget = ToolCallWidget(tool_type="read", target="test.py", args={"path": "test.py"})
        self.assertFalse(widget.is_expandable())

    def test_create_tool_content_strips_trailing_newline(self):
        widget = ToolCallWidget(
            tool_type="create",
            target="test.html",
            args={"path": "test.html", "content": "<html>\n<body>\n</body>\n</html>\n"},
        )
        widget.toggle_expanded()
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, DiffRenderable)
        self.assertIn("<html>", content._text.plain)

    def test_create_tool_content_from_disk_fallback(self):
        file_path = os.path.join(self.test_dir, "saved_file.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("print('from disk')\n")

        widget = ToolCallWidget(
            tool_type="create",
            target=file_path,
            args={"path": file_path},  # no 'content' in args
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, DiffRenderable)
        self.assertIn("print('from disk')", content._text.plain)

    def test_guess_lexer(self):
        widget = ToolCallWidget(tool_type="create", target="script.sh")
        self.assertEqual(widget._guess_lexer("app.py"), "python")
        self.assertEqual(widget._guess_lexer("index.ts"), "typescript")
        self.assertEqual(widget._guess_lexer("style.css"), "css")
        self.assertEqual(widget._guess_lexer("unknown.xyz"), "xyz")

    def test_line_formatting_escapes_markup(self):
        widget = ToolCallWidget(tool_type="create", target="test.py")
        formatted = widget._format_code_with_line_numbers("a = [1, 2]\nb = 'test'")
        self.assertIn("1 │ [/dim]a = \\[1, 2]", formatted)
        self.assertIn("2 │ [/dim]b = 'test'", formatted)

    def test_thinking_widget_toggle_expand(self):
        from widgets.presentation.widgets.chat_messages import ThinkingWidget

        tw = ThinkingWidget("Thinking about problem...")
        tw.finish_thinking(2.5, "Detailed thought process...")
        self.assertFalse(tw.is_expanded)
        self.assertFalse(tw.content_widget.display)

        tw.toggle_expanded()
        self.assertTrue(tw.is_expanded)
        self.assertTrue(tw.content_widget.display)

        tw.toggle_expanded()
        self.assertFalse(tw.is_expanded)
        self.assertFalse(tw.content_widget.display)

    def test_shell_tool_output_escapes_invalid_rich_markup(self):
        widget = ToolCallWidget(
            tool_type="shell",
            target="python -m pytest",
            result_text="Found error: [tag=e1]\n",
            args={"command": "python -m pytest"},
        )
        widget.toggle_expanded()
        content = getattr(widget.content_widget, "_Static__content")
        self.assertEqual(content, "Found error: [tag=e1]")

    def test_chat_view_toggle_expand(self):
        from unittest.mock import PropertyMock, patch

        from widgets.presentation.widgets.chat_container import ChatView
        from widgets.presentation.widgets.chat_messages import ThinkingWidget

        chat_view = ChatView(show_welcome=False)
        tw = ThinkingWidget("Some deep thought")
        tc1 = ToolCallWidget(tool_type="create", target="a.txt", args={"path": "a.txt", "content": "1"})
        tc2 = ToolCallWidget(tool_type="create", target="b.txt", args={"path": "b.txt", "content": "2"})

        with patch.object(ChatView, "children", new_callable=PropertyMock, return_value=[tw, tc1, tc2]):
            # Default ("all") -> expands all blocks if any collapsed
            chat_view.toggle_expand("all")
            self.assertTrue(tc2.is_expanded)
            self.assertTrue(tc1.is_expanded)
            self.assertTrue(tw.is_expanded)

            # Toggling again when all expanded -> collapses all
            chat_view.toggle_expand("all")
            self.assertFalse(tc2.is_expanded)
            self.assertFalse(tc1.is_expanded)
            self.assertFalse(tw.is_expanded)

            # Mode "last" -> toggles last block only
            chat_view.toggle_expand("last")
            self.assertTrue(tc2.is_expanded)
            self.assertFalse(tc1.is_expanded)
            self.assertFalse(tw.is_expanded)

    def test_guess_lexer_cleans_urls(self):
        widget = ToolCallWidget(tool_type="web_fetch", target="https://example.com/script.py?v=2#L10")
        self.assertEqual(widget._guess_lexer("https://example.com/script.py?v=2#L10"), "python")
        self.assertEqual(widget._guess_lexer("https://example.com/style.css?query=abc"), "css")
        self.assertEqual(widget._guess_lexer("https://example.com/data.json"), "json")

    def test_web_fetch_tool_not_expandable(self):
        url = "https://example.com/doc.html"
        widget = ToolCallWidget(tool_type="web_fetch", target=url, args={"url": url})
        self.assertFalse(widget.is_expandable())

    def test_error_and_cancelled_tools_not_expandable_except_shell(self):
        # Error/cancelled results are agent feedback, not user content.
        err = ToolCallWidget(tool_type="edit", target="a.py", args={"path": "a.py"}, status="error")
        self.assertFalse(err.is_expandable())
        canc = ToolCallWidget(tool_type="create", target="a.txt", args={}, status="cancelled")
        self.assertFalse(canc.is_expandable())
        # Shell is always expandable regardless of status (output/returncode useful).
        shell_err = ToolCallWidget(tool_type="shell", target="echo x", args={}, status="error")
        self.assertTrue(shell_err.is_expandable())
        shell_canc = ToolCallWidget(tool_type="shell", target="echo x", args={}, status="cancelled")
        self.assertTrue(shell_canc.is_expandable())

    def test_running_and_done_edit_still_expandable(self):
        done = ToolCallWidget(tool_type="edit", target="a.py", result_text="done", args={"path": "a.py"})
        done.set_result("done", status="done")
        self.assertTrue(done.is_expandable())
        running = ToolCallWidget(tool_type="create", target="a.txt", args={})
        running.status = "running"
        self.assertTrue(running.is_expandable())

    def test_ask_user_display_no_qa_prefix(self):
        widget = ToolCallWidget(
            tool_type="ask_user",
            target="ask_user",
            result_text="What is your name?\nJohnston",
            args={"questions": [{"question": "What is your name?", "options": ["Johnston"]}]},
        )
        kind, value = widget._compute_content()
        self.assertEqual(kind, "raw")
        self.assertIn("What is your name?", value.plain)
        self.assertIn("Johnston", value.plain)

    def test_ask_user_display_multi_questions_and_no_response(self):
        widget = ToolCallWidget(
            tool_type="ask_user",
            target="ask_user",
            result_text="1. First?\nYes\n\n2. Second?\n(No response)",
            args={
                "questions": [
                    {"question": "First?", "options": ["Yes", "No"]},
                    {"question": "Second?", "options": ["A", "B"]},
                ]
            },
        )
        kind, value = widget._compute_content()
        self.assertEqual(kind, "raw")
        expected = "1. First?\nYes\n\n2. Second?\n(No response)"
        self.assertEqual(value.plain, expected)

    def test_shell_running_bg_task_click_toggles_expansion(self):
        task_mock = MagicMock()
        task_mock.task_id = "task-123"
        task_mock.kind = "shell"
        task_mock.is_running = True
        self.mock_app.task_manager = [task_mock]

        widget = ToolCallWidget(
            tool_type="shell",
            target="sleep 10",
            result_text="[Background Task ID: task-123] 'sleep 10' moved to background.",
            args={"command": "sleep 10"},
        )
        self.assertTrue(widget.is_clickable_header())
        event = MagicMock()
        self.assertFalse(widget.is_expanded)
        widget.on_click(event)
        event.stop.assert_called_once()
        self.assertTrue(widget.is_expanded)
        self.mock_app.push_screen.assert_not_called()

    def test_shell_completed_bg_task_click_toggles_expansion(self):
        task_mock = MagicMock()
        task_mock.task_id = "task-123"
        task_mock.kind = "shell"
        task_mock.is_running = False
        self.mock_app.task_manager = [task_mock]

        widget = ToolCallWidget(
            tool_type="shell",
            target="echo ok",
            result_text="[Background Task ID: task-123] 'echo ok' moved to background.\nok",
            args={"command": "echo ok"},
        )
        event = MagicMock()
        self.assertFalse(widget.is_expanded)
        widget.on_click(event)
        self.assertTrue(widget.is_expanded)
        self.mock_app.push_screen.assert_not_called()

    def test_shell_stays_expanded_when_backgrounded_by_user(self):
        """ctrl+b on a foreground shell: expansion stays open, live output kept."""
        widget = ToolCallWidget(
            tool_type="shell",
            target="long_job",
            args={"command": "long_job"},
        )
        widget.append_shell_output("line 1\n")
        widget.toggle_expanded()
        widget.set_result("[Background Task ID: bg_1] 'long_job' moved to background by user after 2.0s.", status="running")
        # Expansion must not be closed by the ctrl+b transition
        self.assertTrue(widget.is_expanded)
        # Live streamed output must not be overwritten by the transient banner
        self.assertIn("line 1", widget.result_text)
        self.assertNotIn("moved to background", widget.result_text)
        # Task id still parsed for the completion repaint
        self.assertEqual(widget.background_task_id, "bg_1")

    def test_shell_bg_banner_not_put_into_result_text_when_no_live_output(self):
        """Explicit background=true launch: result_text stays clean without system banner."""
        widget = ToolCallWidget(
            tool_type="shell",
            target="server",
            args={"command": "server"},
        )
        widget.set_result("[Background Task ID: bg_2] 'server' moved to background.", status="running")
        self.assertNotIn("moved to background", widget.result_text)
        self.assertEqual(widget.background_task_id, "bg_2")
        self.assertFalse(widget.is_expanded)

    def test_shell_completion_repaint_replaces_output(self):
        """Background completion repaints the card with the truncated final text."""
        widget = ToolCallWidget(
            tool_type="shell",
            target="long_job",
            args={"command": "long_job"},
        )
        widget.append_shell_output("partial\n")
        widget.set_result("[Background Task ID: bg_3] 'long_job' moved to background by user after 1.0s.", status="running")
        widget.set_result("[Output truncated: showing last 4000 chars (80 lines).]\nfinal output", status="done")
        self.assertEqual(widget.status, "done")
        self.assertIn("final output", widget.result_text)
        self.assertNotIn("partial", widget.result_text)


if __name__ == "__main__":
    unittest.main()
