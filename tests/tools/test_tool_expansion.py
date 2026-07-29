import os
import tempfile
import unittest
from unittest.mock import MagicMock

from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text
from textual._context import active_app

from widgets.chat_view import ToolCallWidget


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
        self.assertIsInstance(content, Text)
        rendered_plain = content.plain
        self.assertIn("7 - def multiply(a, b):", rendered_plain)
        self.assertIn("9 + def multiply(a: float, b: float) -> float:", rendered_plain)
        self.assertIn("10 +     return a * b", rendered_plain)

    def test_shell_tool_append_output(self):
        widget = ToolCallWidget(
            tool_type="shell",
            target="echo 'live stream'",
            args={"command": "echo 'live stream'"}
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)

        widget.append_bash_output("line 1\n")
        widget.append_bash_output("line 2\n")

        content = getattr(widget.content_widget, "_Static__content")
        self.assertEqual(content, "line 1\nline 2")

    def test_read_tool_clean_rendering(self):
        raw_read_output = (
            "=== Lines 5-7 of 59 in test.py ===\n"
            " 5 | def foo():\n"
            " 6 |     return 'bar'\n"
            " 7 | \n"
        )
        widget = ToolCallWidget(
            tool_type="read",
            target="test.py",
            result_text=raw_read_output,
            args={"path": "test.py"}
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)

        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, Syntax)
        self.assertEqual(content.start_line, 5)
        self.assertEqual(content.code, "def foo():\n    return 'bar'")

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

    def test_analyze_image_expandable(self):
        widget = ToolCallWidget(
            tool_type="analyze_image",
            target="image.png",
            result_text="[Vision Analysis]: cat",
            args={"path": "image.png"}
        )
        self.assertTrue(widget.is_expandable())
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)


if __name__ == "__main__":
    unittest.main()

