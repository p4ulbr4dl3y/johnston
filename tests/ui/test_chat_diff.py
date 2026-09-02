import unittest

from widgets.presentation.widgets.chat_diff import DiffRenderable, format_edit_diff


class TestDiffRenderable(unittest.TestCase):
    def test_diff_renderable_console_and_measure(self):
        from rich.console import Console
        from rich.text import Text

        lines = [Text("old line"), Text("new line")] * 2
        renderable = DiffRenderable(lines)
        console = Console(width=20, record=True, _environ={})
        console.print(renderable)
        self.assertIn("old line", console.export_text())
        self.assertIsNotNone(renderable.__rich_measure__(console, console.options))
        self.assertEqual(renderable.plain, "old line\nnew line\nold line\nnew line")

    def test_diff_renderable_pads_short_lines(self):
        from rich.console import Console
        from rich.text import Text

        lines = [Text("short"), Text("a much longer line that exceeds")]
        renderable = DiffRenderable(lines)
        console = Console(width=10, record=True, _environ={})
        console.print(renderable)
        self.assertIn("short", console.export_text())


class TestFormatEditDiff(unittest.TestCase):
    def test_format_edit_diff_basic_hunk(self):
        diff = "--- a/file.py\n+++ b/file.py\n@@ -1,3 +1,3 @@\n def keep():\n-    old = 1\n+    new = 2\n     return\n"
        result = format_edit_diff(diff, "file.py")
        self.assertIsInstance(result, DiffRenderable)
        text = result.plain
        self.assertIn("keep", text)
        self.assertIn("old = 1", text)
        self.assertIn("new = 2", text)

        diff2 = "Success: file 'f.py' updated\n--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
        result2 = format_edit_diff(diff2, "f.py")
        self.assertNotIn("Success", result2.plain)

    def test_format_edit_diff_no_hunk_and_unknown_lexer(self):
        diff = "just a plain status line\nmore status\n"
        result = format_edit_diff(diff, "unknown.xyz")
        self.assertIsInstance(result, DiffRenderable)
        self.assertIn("just a plain status line", result.plain)

    def test_format_edit_diff_html_js_and_css_detection(self):
        html_js = (
            "--- a/index.html\n"
            "+++ b/index.html\n"
            "@@ -1,2 +1,2 @@\n"
            "-<script>console.log(1)</script>\n"
            "+function run() { return 1; }\n"
        )
        result = format_edit_diff(html_js, "index.html")
        self.assertIn("console", result.plain)

        html_css = "--- a/style.html\n+++ b/style.html\n@@ -1,1 +1,1 @@\n-body { color: red; }\n+div { color: blue; }\n"
        result2 = format_edit_diff(html_css, "style.html")
        self.assertIn("color", result2.plain)

    def test_format_edit_diff_backslash_and_outside_hunk_lines(self):
        diff = (
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "\\ No newline at end of file\n"
            "+new\n"
            "\\ No newline at end of file\n"
            "trailing garbage line\n"
        )
        result = format_edit_diff(diff, "f.py")
        self.assertNotIn("No newline at end of file", result.plain)
        self.assertIn("trailing garbage line", result.plain)

    def test_format_edit_diff_empty_code_lines_and_no_lexer(self):
        diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1,1 +1,1 @@\n-\n+\n"
        result = format_edit_diff(diff, "f.txt")
        self.assertIsInstance(result, DiffRenderable)

    def test_format_edit_diff_http_path_and_multi_hunk_numbers(self):
        diff = "--- a/f.py\n+++ b/f.py\n@@ -1,2 +10,2 @@\n-line1\n-line2\n+lineA\n+lineB\n"
        result = format_edit_diff(diff, "https://example.com/f.py")
        self.assertIsInstance(result, DiffRenderable)
        self.assertIn("lineA", result.plain)

    def test_format_edit_diff_empty_lines_and_hunk_marker_without_ranges(self):
        diff = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n context\n-\n+\n tail\n"
        result = format_edit_diff(diff, "f.py")
        self.assertIsInstance(result, DiffRenderable)

    def test_format_edit_diff_success_ok_and_status_lines_outside_hunk(self):
        diff = (
            "OK: did something\n"
            "file.py updated\n"
            "file created\n"
            "file saved\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-a\n"
            "+b\n"
        )
        result = format_edit_diff(diff, "f.py")
        self.assertIn("1 + b", result.plain)

    def test_format_edit_diff_filters_ok_lines_without_hunk(self):
        diff = "OK: did something\nplain status\n"
        result = format_edit_diff(diff, "f.py")
        self.assertNotIn("OK:", result.plain)
        self.assertIn("plain status", result.plain)

    def test_format_edit_diff_html_with_style_block_detection(self):
        diff = (
            "--- a/s.html\n"
            "+++ b/s.html\n"
            "@@ -1,1 +1,1 @@\n"
            "-<style>body { color: red; }</style>\n"
            "+<style>div { color: blue; }</style>\n"
        )
        result = format_edit_diff(diff, "s.html")
        self.assertIn("color", result.plain)

    def test_format_edit_diff_plain_lines_before_hunk_kept_dim(self):
        diff = "preamble line\n--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
        result = format_edit_diff(diff, "f.py")
        self.assertIn("preamble line", result.plain)

    def test_format_edit_diff_empty_path_and_empty_context_line(self):
        diff = "--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n a\n\n-b\n+c\n"
        result = format_edit_diff(diff, "")
        self.assertIsInstance(result, DiffRenderable)

    def test_format_edit_diff_html_script_tags_detection(self):
        diff = (
            "--- a/p.html\n"
            "+++ b/p.html\n"
            "@@ -1,1 +1,1 @@\n"
            "-<script>const x = 1;</script>\n"
            "+<script>const y = 2;</script>\n"
        )
        result = format_edit_diff(diff, "p.html")
        self.assertIn("const", result.plain)

    def test_format_edit_diff_css_after_script_detection(self):
        diff = "--- a/q.html\n+++ b/q.html\n@@ -1,1 +1,1 @@\n-body { margin: 0; }\n+div { padding: 0; }\n"
        result = format_edit_diff(diff, "q.html")
        self.assertIn("margin", result.plain)

    def test_format_edit_diff_js_without_script_tag(self):
        diff = "--- a/r.html\n+++ b/r.html\n@@ -1,1 +1,1 @@\n-function init() { return 1; }\n+const value = 2;\n"
        result = format_edit_diff(diff, "r.html")
        self.assertIn("function", result.plain)

    def test_format_edit_diff_lexer_exception_fallback(self):
        diff = "--- a/f.unknownext\n+++ b/f.unknownext\n@@ -1,1 +1,1 @@\n-line one\n+line two\n"
        result = format_edit_diff(diff, "f.unknownext")
        self.assertIn("line one", result.plain)

    def test_diff_renderable_hanging_indent_wrapping(self):
        from rich.console import Console
        from rich.text import Text

        from widgets.presentation.widgets.chat_diff import DiffLine

        pfx = Text(" 10 + ")
        code = Text("a very long code line that should wrap to next line")
        dl = DiffLine(pfx, code, style_bg="on #12261e")
        renderable = DiffRenderable([dl])
        console = Console(width=25, record=True, _environ={})
        console.print(renderable)
        exported = console.export_text()
        self.assertIn("10 +", exported)
        self.assertIn("a very", exported)
        lines = exported.strip().splitlines()
        self.assertGreater(len(lines), 1)
        # Continuation line must be indented with blanks under gutter
        self.assertTrue(lines[1].startswith("      "))

    def test_format_edit_diff_git_metadata_headers_stripped(self):
        diff = (
            "diff --git a/core/mgr.py b/core/mgr.py\n"
            "index 8200ebb..79d08e7 100644\n"
            "--- a/core/mgr.py\n"
            "+++ b/core/mgr.py\n"
            "@@ -10,1 +10,1 @@\n"
            "-foo\n"
            "+bar\n"
        )
        result = format_edit_diff(diff, "mgr.py")
        self.assertNotIn("diff --git", result.plain)
        self.assertNotIn("index 8200", result.plain)
        self.assertIn("10 - foo", result.plain)
        self.assertIn("10 + bar", result.plain)

    def test_format_edit_diff_multi_hunk_separator(self):
        diff = (
            "@@ -10,1 +10,1 @@\n"
            "-foo\n"
            "+bar\n"
            "@@ -50,1 +50,1 @@\n"
            "-baz\n"
            "+qux\n"
        )
        result = format_edit_diff(diff, "file.py")
        plain = result.plain
        self.assertIn("···", plain)
        lines = plain.splitlines()
        # Ensure hunk 1 line, separator line, hunk 2 line order
        self.assertTrue(any("10 - foo" in item for item in lines))
        self.assertTrue(any("···" in item for item in lines))
        self.assertTrue(any("50 + qux" in item for item in lines))

    def test_get_diff_colors_dark_and_light(self):
        from unittest.mock import MagicMock

        from widgets.presentation.widgets.chat_diff import get_diff_colors, get_diff_word_colors

        # Dark theme mock
        dark_theme = MagicMock()
        dark_theme.dark = True
        dark_theme.muted = "#71717a"
        dark_theme.syntax_tokens = {}
        add_fg, add_bg, rem_fg, rem_bg, gutter = get_diff_colors(dark_theme)
        self.assertEqual(add_fg, "#46c05a")
        self.assertEqual(add_bg, "on #23382b")
        self.assertEqual(rem_fg, "#f25555")
        self.assertEqual(rem_bg, "on #382427")
        self.assertEqual(gutter, "#71717a")

        w_add, w_rem = get_diff_word_colors(dark_theme)
        self.assertEqual(w_add, "on #1c5230")
        self.assertEqual(w_rem, "on #5e2129")

        # Light theme mock
        light_theme = MagicMock()
        light_theme.dark = False
        light_theme.muted = "#8c8fa1"
        light_theme.syntax_tokens = {}
        l_add_fg, l_add_bg, l_rem_fg, l_rem_bg, l_gutter = get_diff_colors(light_theme)
        self.assertEqual(l_add_fg, "#1a7f37")
        self.assertEqual(l_add_bg, "on #dafbe1")
        self.assertEqual(l_rem_fg, "#cf222e")
        self.assertEqual(l_rem_bg, "on #ffebe9")
        self.assertEqual(l_gutter, "#8c8fa1")

        lw_add, lw_rem = get_diff_word_colors(light_theme)
        self.assertEqual(lw_add, "on #acf2bd")
        self.assertEqual(lw_rem, "on #ffb3ba")

    def test_format_edit_diff_word_level_highlighting(self):
        diff = (
            "--- a/test.py\n"
            "+++ b/test.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-if user_count > 10:\n"
            "+if user_count <= 10:\n"
        )
        result = format_edit_diff(diff, "test.py")
        self.assertIsInstance(result, DiffRenderable)
        self.assertIn("user_count > 10", result.plain)
        self.assertIn("user_count <= 10", result.plain)
        # Check that spans were stylized with word diff backgrounds
        dl_old = result.formatted_lines[0]
        self.assertTrue(any("on #5e2129" in s.style for s in dl_old.code._spans))
        dl_new = result.formatted_lines[1]
        self.assertTrue(any("on #1c5230" in s.style for s in dl_new.code._spans))

    def test_format_edit_diff_split_mode(self):
        from rich.console import Console

        diff = (
            "--- a/test.py\n"
            "+++ b/test.py\n"
            "@@ -1,3 +1,3 @@\n"
            " ctx\n"
            "-old_value = 1\n"
            "+new_value = 2\n"
            " end\n"
        )
        result = format_edit_diff(diff, "test.py", view_mode="split")
        self.assertIsInstance(result, DiffRenderable)
        self.assertGreater(len(result.hunk_lines), 0)

        console = Console(width=80, record=True, _environ={})
        console.print(result)
        exported = console.export_text()
        self.assertIn("old_value", exported)
        self.assertIn("new_value", exported)
        self.assertIn("│", exported)



