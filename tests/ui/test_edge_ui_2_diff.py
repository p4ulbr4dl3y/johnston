"""Edge-case tests for widgets/chat_diff diff rendering.

Detectors for real ordering bugs when old and new hunk line counts differ.
"""

import unittest

from widgets.chat_diff import DiffRenderable, format_edit_diff


class TestDiffRenderable(unittest.TestCase):
    def test_empty_line_list_measure(self):
        """__rich_measure__ on an empty DiffRenderable must not raise."""
        renderable = DiffRenderable([])
        from rich.console import Console

        console = Console(width=20)
        options = console.options
        measure = renderable.__rich_measure__(console, options)
        # Measure must return a (min, max) pair.
        self.assertEqual(len(tuple(measure)), 2)

    def test_empty_line_list_console(self):
        from rich.console import Console

        renderable = DiffRenderable([])
        console = Console(width=20)
        self.assertIsNotNone(console.render(renderable))


class TestFormatEditDiffNumbering(unittest.TestCase):
    def test_removed_line_uses_new_side_column(self):
        """Numbering uses a single (new-side) column. A `-` line in a hunk with
        differing old/new counts still takes the running new-side counter."""
        diff = "@@ -5,3 +10,1 @@\nctx\n-old\n+new\n"
        result = format_edit_diff(diff, "f.py")
        # ctx is new-line 10; the removed line keeps the new-side counter (11).
        self.assertIn("11 - old", result.plain)

    def test_removed_line_new_numbering_exact(self):
        diff = "@@ -1,3 +1,3 @@\nctx\n-old\n+new\nctx2\n"
        result = format_edit_diff(diff, "f.py")
        # ctx new 1, removed line new-line 2, +new new-line 2, ctx2 new-line 3
        self.assertIn("1   ctx", result.plain)
        self.assertIn("2 - old", result.plain)
        self.assertIn("2 + new", result.plain)
        self.assertIn("3   ctx2", result.plain)


class TestFormatEditDiffEmpty(unittest.TestCase):
    def test_empty_diff_returns_renderable(self):
        result = format_edit_diff("", "f.py")
        self.assertIsInstance(result, DiffRenderable)

    def test_hunk_marker_only_no_context(self):
        result = format_edit_diff("--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n", "f.py")
        self.assertIsInstance(result, DiffRenderable)


if __name__ == "__main__":
    unittest.main()
