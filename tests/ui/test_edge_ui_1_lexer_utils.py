"""Edge-case tests for widgets/lexer_utils.py (bug-hunting round)."""
import unittest
from unittest.mock import patch

from widgets.lexer_utils import generate_chunk_unified_diff, guess_lexer_name, lex_block_to_line_texts


class TestGuessLexerName(unittest.TestCase):
    def test_empty_path_returns_text(self):
        self.assertEqual(guess_lexer_name(""), "text")

    def test_whitespace_only_path_returns_text(self):
        self.assertEqual(guess_lexer_name("   "), "text")

    def test_none_path_returns_text(self):
        self.assertEqual(guess_lexer_name(None), "text")

    def test_known_extension_lowercased(self):
        self.assertEqual(guess_lexer_name("Foo.PY"), "python")

    def test_unknown_extension_returns_ext(self):
        self.assertEqual(guess_lexer_name("file.unknown_ext"), "unknown_ext")

    def test_extensionless_returns_text(self):
        self.assertEqual(guess_lexer_name("Makefile"), "text")

    def test_url_uses_path_component(self):
        self.assertEqual(guess_lexer_name("https://host.com/x/main.py?raw=1"), "python")

    def test_multibyte_in_path_is_ignored(self):
        self.assertEqual(guess_lexer_name("файл.go"), "go")


class TestLexBlockToLineTexts(unittest.TestCase):
    def _texts(self, lines, lexer=None):
        return lex_block_to_line_texts(lines, lexer)

    def test_empty_lines_returns_empty(self):
        self.assertEqual(self._texts([]), [])

    def test_none_lines_raises(self):
        with self.assertRaises(Exception):
            self._texts([None])

    def test_no_lexer_returns_plain_texts(self):
        out = self._texts(["a", "b"], lexer=None)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].plain, "a")
        self.assertEqual(out[1].plain, "b")

    def test_multiline_input_preserves_line_count(self):
        from pygments.lexers import PythonLexer

        lines = ["def f():", "    return 1", "", "# done"]
        out = self._texts(lines, PythonLexer())
        self.assertEqual(len(out), len(lines))
        joined = "\n".join(t.plain for t in out)
        self.assertEqual(joined, "\n".join(lines))

    def test_whitespace_only_lines_preserved(self):
        from pygments.lexers import PythonLexer

        lines = ["   ", "", "    x"]
        out = self._texts(lines, PythonLexer())
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0].plain, "   ")

    def test_lexer_exception_falls_back_to_plain(self):
        with patch(
            "widgets.lexer_utils.pygments.lex", side_effect=RuntimeError("boom")
        ):
            out = self._texts(["a", "b"], lexer=object())
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].plain, "a")

    def test_crlf_lines_do_not_corrupt_text(self):
        # CRLF pasted code must not leak a stray "\r" into rendered tokens or
        # produce phantom lines. Values are split on "\n" only, so a trailing
        # "\r" in the last token value would otherwise stay embedded.
        from pygments.lexers import PythonLexer

        crlf_input = ["def f():\r", "    return 1\r"]
        out = self._texts(crlf_input, PythonLexer())
        self.assertEqual(len(out), len(crlf_input))
        for text in out:
            self.assertNotIn("\r", text.plain)

    def test_embedded_newline_in_single_entry_loses_no_content(self):
        # A single list element carrying an embedded newline must keep all its
        # content across the rendered lines (no silent trimming).
        from pygments.lexers import PythonLexer

        code_lines = ["def f():\n    return 1"]
        out = self._texts(code_lines, PythonLexer())
        rendered = "\n".join(t.plain for t in out)
        self.assertIn("return 1", rendered)


class TestGenerateChunkUnifiedDiff(unittest.TestCase):
    def test_empty_both_returns_empty(self):
        self.assertEqual(generate_chunk_unified_diff("", ""), [])

    def test_adjusts_hunk_start_line(self):
        d = generate_chunk_unified_diff("a\nb", "a\nb\nc", file_path="x.txt", start_line=7)
        self.assertTrue(any(line.startswith("@@") for line in d))
        self.assertTrue(any(line.startswith("@@ -7") for line in d))


if __name__ == "__main__":
    unittest.main()
