"""Tests for CLI formatter module."""
from __future__ import annotations

import unittest

from johnston_core.interfaces.cli.formatter import (
    format_key_status,
    format_kv,
    format_status,
    format_table,
    truncate_str,
)


class TestCLIFormatter(unittest.TestCase):
    def test_truncate_str(self):
        self.assertEqual(truncate_str("hello", 10), "hello")
        self.assertEqual(truncate_str("hello world", 8), "hello...")
        self.assertEqual(truncate_str("hello", 3), "hel")
        self.assertEqual(truncate_str("hello", 0), "")

    def test_format_table_max_width_truncation(self):
        headers = ["ColA", "ColB"]
        rows = [["very_long_string_that_exceeds_columns", "another_very_long_string"]]
        rendered = format_table(headers, rows, max_width=30)
        for line in rendered.splitlines():
            self.assertLessEqual(len(line), 30)

    def test_format_table_flattens_newlines(self):
        headers = ["ColA", "ColB"]
        rows = [["line1\nline2", "single"]]
        rendered = format_table(headers, rows)
        lines = rendered.splitlines()
        self.assertEqual(len(lines), 3)  # Header, divider, 1 data row
        self.assertIn("line1 line2", lines[2])

    def test_format_status(self):
        self.assertIn("✓", format_status(True, colorize=False))
        self.assertIn("✗", format_status(False, colorize=False))

    def test_format_key_status(self):
        self.assertEqual(format_key_status(True, colorize=False), "[set]")
        self.assertEqual(format_key_status(False, colorize=False), "[unset]")

    def test_format_kv(self):
        rendered = format_kv([("a", 1), ("b", "hello")])
        self.assertIn("a: 1", rendered)
        self.assertIn("b: hello", rendered)
