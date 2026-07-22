import os
import tempfile
import unittest

from rich.syntax import Syntax

from widgets.chat_view import ToolCallWidget


class TestToolExpansion(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tool_call_widget_init(self):
        widget = ToolCallWidget(
            tool_type="Create",
            target="test.txt",
            result_text="Success",
            args={"path": "test.txt", "content": "hello\nworld"}
        )
        widget.render_header()
        self.assertFalse(widget.is_expanded)
        self.assertEqual(widget.tool_type, "Create")
        self.assertEqual(widget.args["content"], "hello\nworld")
        self.assertIn("▶", str(widget.header_label.render()))

    def test_tool_call_widget_toggle_expand_syntax(self):
        widget = ToolCallWidget(
            tool_type="Create",
            target="test.py",
            args={"path": "test.py", "content": "def foo():\n    return 42"}
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        self.assertIn("▼", str(widget.header_label.render()))
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, Syntax)
        self.assertEqual(content.lexer.name, "Python")

        widget.toggle_expanded()
        self.assertFalse(widget.is_expanded)
        self.assertIn("▶", str(widget.header_label.render()))

    def test_create_tool_content_from_disk_fallback(self):
        file_path = os.path.join(self.test_dir, "saved_file.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("print('from disk')\n")

        widget = ToolCallWidget(
            tool_type="Create",
            target=file_path,
            args={"path": file_path}  # no 'content' in args
        )
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        content = getattr(widget.content_widget, "_Static__content")
        self.assertIsInstance(content, Syntax)

    def test_guess_lexer(self):
        widget = ToolCallWidget(tool_type="Create", target="script.sh")
        self.assertEqual(widget._guess_lexer("app.py"), "python")
        self.assertEqual(widget._guess_lexer("index.ts"), "typescript")
        self.assertEqual(widget._guess_lexer("style.css"), "css")
        self.assertEqual(widget._guess_lexer("unknown.xyz"), "xyz")

    def test_line_formatting_escapes_markup(self):
        widget = ToolCallWidget(tool_type="Create", target="test.py")
        formatted = widget._format_code_with_line_numbers("a = [1, 2]\nb = 'test'")
        self.assertIn("1 │ [/dim]a = \\[1, 2]", formatted)
        self.assertIn("2 │ [/dim]b = 'test'", formatted)


if __name__ == "__main__":
    unittest.main()
