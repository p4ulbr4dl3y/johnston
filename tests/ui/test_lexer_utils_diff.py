"""Tests for chunk-level unified diff generation in widgets/lexer_utils.py."""

import unittest
from unittest.mock import patch

from widgets.lexer_utils import build_edit_diff_text, generate_chunk_unified_diff


class TestGenerateChunkUnifiedDiff(unittest.TestCase):
    def test_empty_both_returns_empty(self):
        self.assertEqual(generate_chunk_unified_diff("", "", "f.py"), [])

    def test_replacement_chunk(self):
        lines = generate_chunk_unified_diff("a\nb\nc\n", "a\nX\nc\n", "foo.py", 5)
        self.assertIn("--- foo.py", lines)
        self.assertIn("+++ foo.py", lines)
        self.assertTrue(any(line.startswith("@@ -5,") for line in lines))
        self.assertIn("-b", lines)
        self.assertIn("+X", lines)
        # git metadata lines are stripped
        self.assertFalse(any(line.startswith("diff --git") for line in lines))
        self.assertFalse(any(line.startswith("index ") for line in lines))

    def test_single_line(self):
        lines = generate_chunk_unified_diff("x", "y", "f.py", 10)
        self.assertTrue(any(line.startswith("@@ -10,1 +10,1 @@") for line in lines))

    def test_addition_chunk(self):
        lines = generate_chunk_unified_diff("", "a\nb", "f.py", 3)
        self.assertTrue(any(line.startswith("@@ -3,") for line in lines))
        self.assertIn("+a", lines)

    def test_removal_chunk(self):
        lines = generate_chunk_unified_diff("a\nb", "", "f.py", 7)
        self.assertTrue(any(line.startswith("@@ -7,") for line in lines))
        self.assertIn("-a", lines)

    def test_fallback_when_git_unavailable(self):
        with patch("core.git_utils.run_git", side_effect=OSError("no git")):
            lines = generate_chunk_unified_diff("a\nb\n", "a\nc\n", "f.py", 2)
        self.assertIn("-b", lines)
        self.assertIn("+c", lines)


class TestBuildEditDiffText(unittest.TestCase):
    def test_chunks_are_concatenated(self):
        args = {
            "edits": [
                {"old_str": "a\nb", "new_str": "a\nc", "start_line": 1},
                {"old_str": "x", "new_str": "y", "start_line": 5},
            ]
        }
        out = build_edit_diff_text(args, "x.py", "edit")
        self.assertIn("-b", out)
        self.assertIn("+c", out)
        self.assertIn("-x", out)
        self.assertIn("+y", out)

    def test_old_str_new_str_form(self):
        out = build_edit_diff_text({"old_str": "a\nb", "new_str": "a\nc"}, "x.py", "edit")
        self.assertIn("-b", out)
        self.assertIn("+c", out)

    def test_non_dict_args_returns_empty(self):
        self.assertEqual(build_edit_diff_text("not a dict", "x.py", "edit"), "")

    def test_empty_returns_empty(self):
        self.assertEqual(build_edit_diff_text({}, "x.py", "edit"), "")


class TestLexBlockToLineTexts(unittest.TestCase):
    def test_preserves_leading_blank_lines(self):
        from pygments.lexers import get_lexer_by_name

        from widgets.lexer_utils import lex_block_to_line_texts

        code_lines = ["", "", "def main():", "    pass"]
        lexer = get_lexer_by_name("python")
        res = lex_block_to_line_texts(code_lines, lexer)
        self.assertEqual(len(res), 4)
        self.assertEqual(res[0].plain, "")
        self.assertEqual(res[1].plain, "")
        self.assertEqual(res[2].plain, "def main():")
        self.assertEqual(res[3].plain, "    pass")


if __name__ == "__main__":
    unittest.main()
