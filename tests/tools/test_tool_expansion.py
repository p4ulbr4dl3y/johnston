import os
import tempfile
import unittest
from unittest.mock import MagicMock

from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text
from textual._context import active_app

from widgets.chat_view import DiffRenderable, ToolCallWidget


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
            args={"path": "test.txt", "content": "hello\nworld"}
        )
        widget.render_header()
        self.assertFalse(widget.is_expanded)
        self.assertEqual(widget.tool_type, "create")
        self.assertEqual(widget.args["content"], "hello\nworld")
        self.assertIn("⚙", str(widget.header_label.render()))

    def test_tool_call_widget_toggle_expand_syntax(self):
        widget = ToolCallWidget(
            tool_type="create",
            target="test.py",
            args={"path": "test.py", "content": "def foo():\n    return 42"}
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        self.assertIn("⚙", str(widget.header_label.render()))
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, Syntax)
        self.assertEqual(content.lexer.name, "Python")

        widget.toggle_expanded()
        self.assertFalse(widget.is_expanded)

    def test_edit_tool_toggle_expand_diff(self):
        diff_text = (
            "--- test.py (old)\n"
            "+++ test.py (new)\n"
            "@@ -7,1 +9,2 @@\n"
            "-def multiply(a, b):\n"
            "+def multiply(a: float, b: float) -> float:\n"
            "+    return a * b\n"
        )
        widget = ToolCallWidget(
            tool_type="edit",
            target="test.py",
            result_text=diff_text,
            args={"path": "test.py", "old_string": "def multiply(a, b):", "new_string": "def multiply(a: float, b: float) -> float:\n    return a * b"}
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
            tool_type="edit",
            target="index.html",
            result_text=diff_text,
            args={"path": "index.html"}
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
        error_text = "Error: target_content not found between lines 10 and 20 in 'test.py'."
        widget = ToolCallWidget(
            tool_type="edit",
            target="test.py",
            result_text=error_text,
            args={"path": "test.py", "target_content": "foo", "replacement_content": "bar"}
        )
        widget.set_result(error_text)
        widget.toggle_expanded()
        self.assertEqual(widget.status, "error")
        content = getattr(widget.content_widget, "_Static__content")
        self.assertEqual(content, error_text)

    def test_hints_stripped_from_ui_display_but_retained_in_result_text(self):
        full_text = "Error: target_content not found.\n\n[Hint: Nearest matching code in 'test.py' around line 15]:\nline 1\nline 2"
        widget = ToolCallWidget(
            tool_type="edit",
            target="test.py",
            result_text=full_text,
            args={"path": "test.py"}
        )
        widget.set_result(full_text, is_error=True)
        widget.toggle_expanded()

        # result_text must keep [Hint:] for agent
        self.assertEqual(widget.result_text, full_text)
        # UI content widget must strip [Hint:] block
        content = getattr(widget.content_widget, "_Static__content")
        self.assertNotIn("[Hint:", content)
        self.assertIn("Error: target_content not found.", content)

    def test_create_tool_error_display(self):
        error_text = "Error: '/some/dir' is a directory, cannot overwrite with file."
        widget = ToolCallWidget(
            tool_type="create",
            target="/some/dir",
            result_text=error_text,
            args={"path": "/some/dir", "content": "some content"}
        )
        widget.set_result(error_text)
        widget.toggle_expanded()
        self.assertEqual(widget.status, "error")
        content = getattr(widget.content_widget, "_Static__content")
        self.assertEqual(content, error_text)

    def test_update_plan_error_display(self):
        error_text = "Error: 'plan' parameter must be a non-empty list of items."
        widget = ToolCallWidget(
            tool_type="update_plan",
            target="plan",
            result_text=error_text,
            args={"plan": []}
        )
        widget.set_result(error_text)
        widget.toggle_expanded()
        self.assertEqual(widget.status, "error")
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
            tool_type="edit",
            target="index.html",
            result_text=diff_text,
            args={"path": "index.html"}
        )
        widget.toggle_expanded()
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, (Text, DiffRenderable))
        # Check that tokens inside function handleFormSubmit have styles applied (not style=None)
        has_styled_spans = any(span.style is not None for span in content._spans)
        self.assertTrue(has_styled_spans)

        self.assertEqual(content.overflow, "crop")

    def test_edit_tool_html_tags_rendering(self):
        diff_text = (
            "@@ -274,5 +274,5 @@\n"
            "+ </button>\n"
            "+ </form>\n"
            "+ <p id=\"cta-success\">\n"
            "+ Talk to Sales instead\n"
            " </div>\n"
        )
        widget = ToolCallWidget(
            tool_type="edit",
            target="index.html",
            result_text=diff_text,
            args={"path": "index.html"}
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
                "TargetFile": "index.html",
                "TargetContent": "const form = document.getElementById('cta-form');",
                "ReplacementContent": "// CTA form handler\nconst form = document.getElementById('cta-form');",
                "StartLine": 330
            }
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, (Text, DiffRenderable))
        rendered_plain = content.plain
        self.assertIn("330 + // CTA form handler", rendered_plain)
        self.assertIn("331   const form = document.getElementById('cta-form');", rendered_plain)

    def test_edit_tool_multi_replace_chunks(self):
        widget = ToolCallWidget(
            tool_type="multi_edit",
            target="app.py",
            result_text="",
            args={
                "TargetFile": "app.py",
                "ReplacementChunks": [
                    {
                        "TargetContent": "x = 1",
                        "ReplacementContent": "x = 10",
                        "StartLine": 15
                    },
                    {
                        "TargetContent": "y = 2",
                        "ReplacementContent": "y = 20",
                        "StartLine": 45
                    }
                ]
            }
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, (Text, DiffRenderable))
        rendered_plain = content.plain
        self.assertIn("15 - x = 1", rendered_plain)
        self.assertIn("15 + x = 10", rendered_plain)
        self.assertIn("45 - y = 2", rendered_plain)
        self.assertIn("45 + y = 20", rendered_plain)

    def test_shell_tool_append_output(self):
        widget = ToolCallWidget(
            tool_type="shell",
            target="echo 'live stream'",
            args={"command": "echo 'live stream'"}
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)

        widget.append_shell_output("line 1\n")
        widget.append_shell_output("line 2\n")

        content = getattr(widget.content_widget, "_Static__content")
        self.assertEqual(content, "line 1\nline 2")

    def test_read_tool_not_expandable(self):
        widget = ToolCallWidget(
            tool_type="read",
            target="test.py",
            args={"path": "test.py"}
        )
        self.assertFalse(widget.is_expandable())

    def test_create_tool_content_strips_trailing_newline(self):
        widget = ToolCallWidget(
            tool_type="create",
            target="test.html",
            args={"path": "test.html", "content": "<html>\n<body>\n</body>\n</html>\n"}
        )
        widget.toggle_expanded()
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, Syntax)
        self.assertEqual(content.code, "<html>\n<body>\n</body>\n</html>")

    def test_create_tool_content_from_disk_fallback(self):
        file_path = os.path.join(self.test_dir, "saved_file.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("print('from disk')\n")

        widget = ToolCallWidget(
            tool_type="create",
            target=file_path,
            args={"path": file_path}  # no 'content' in args
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, Syntax)

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
        from widgets.chat_view import ThinkingWidget
        tw = ThinkingWidget("Thinking about problem...")
        tw.finish_thinking(2.5, "Detailed thought process...")
        self.assertFalse(tw.is_expanded)
        self.assertFalse(tw.md_widget.display)

        tw.toggle_expanded()
        self.assertTrue(tw.is_expanded)
        self.assertTrue(tw.md_widget.display)

        tw.toggle_expanded()
        self.assertFalse(tw.is_expanded)
        self.assertFalse(tw.md_widget.display)

    def test_format_read_content_strips_nested_line_numbers(self):
        widget = ToolCallWidget(tool_type="read", target="test.log")
        raw = "    150 |     150 | ### Uh oh!"
        clean, start, path = widget._format_read_content(raw, "test.log")
        self.assertEqual(clean, "### Uh oh!")

    def test_format_read_content_strips_hint_lines(self):
        widget = ToolCallWidget(tool_type="read", target="flappy.html")
        raw = "=== Lines 1-30 of 187 in flappy.html ===\n[Hint: File has 187 lines. Use start_line=31 end_line=187 to read next chunk.]\n    1 | <!DOCTYPE html>\n    2 | <html>"
        clean, start, path = widget._format_read_content(raw, "flappy.html")
        self.assertEqual(clean, "<!DOCTYPE html>\n<html>")
        self.assertEqual(start, 1)
        self.assertEqual(path, "flappy.html")



    def test_shell_tool_output_escapes_invalid_rich_markup(self):
        widget = ToolCallWidget(
            tool_type="shell",
            target="python -m pytest",
            result_text="Found error: [tag=e1]\n",
            args={"command": "python -m pytest"}
        )
        widget.toggle_expanded()
        content = getattr(widget.content_widget, "_Static__content")
        self.assertEqual(content, r"Found error: \[tag=e1]")




    def test_chat_view_toggle_expand(self):
        from unittest.mock import PropertyMock, patch

        from widgets.chat_view import ChatView, ThinkingWidget
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
        widget = ToolCallWidget(
            tool_type="web_fetch",
            target=url,
            args={"url": url}
        )
        self.assertFalse(widget.is_expandable())


if __name__ == "__main__":
    unittest.main()

