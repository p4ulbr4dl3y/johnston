"""Edge-case tests for the markdown cleaning helper.

White-box checks on unclosed fences and hard-to-parse content.
"""

import unittest

from widgets.presentation.widgets.chat_markdown import clean_markdown_for_rendering


class TestCleanMarkdownEdgeCases(unittest.TestCase):
    def test_unclosed_fence_appends_closer(self):
        raw = "before\n```python\nprint(1)\n"
        cleaned = clean_markdown_for_rendering(raw)
        self.assertTrue(cleaned.rstrip().endswith("```"))

    def test_unicode_content_preserved(self):
        raw = "привет · 🌍 汉字 हिन्दी em-dash —"
        self.assertEqual(clean_markdown_for_rendering(raw), raw)

    def test_many_blank_lines_outside_fence_collapsed(self):
        raw = "a\n\n\n\n\n\nb"
        self.assertNotIn("\n\n\n", clean_markdown_for_rendering(raw))

    def test_nested_bold_malformed_no_crash(self):
        raw = "**bold **unclosed\n*star*\ntext"
        cleaned = clean_markdown_for_rendering(raw)
        self.assertIn("unclosed", cleaned)
        self.assertIn("text", cleaned)

    def test_empty_fence_body(self):
        raw = "```python\n```"
        self.assertIn("```", clean_markdown_for_rendering(raw))


if __name__ == "__main__":
    unittest.main()
