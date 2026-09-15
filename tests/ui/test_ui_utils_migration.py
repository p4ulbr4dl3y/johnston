"""Tests for TUI utils: text_format, palette, and clipboard."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from johnston.tui.utils.clipboard import copy_to_os_clipboard_async, get_clipboard_image_or_file
from johnston.tui.utils.palette import compute_adaptive_palette, query_terminal_palette
from johnston.tui.utils.text_format import (
    format_duration,
    is_spinner_line,
    process_carriage_returns,
    process_carriage_returns_lines,
    strip_ansi,
    truncate_output,
)


class TestTextFormatUtils(unittest.TestCase):
    def test_strip_ansi(self):
        self.assertEqual(strip_ansi("\033[31mhello\033[0m world"), "hello world")
        self.assertEqual(strip_ansi("plain text"), "plain text")

    def test_truncate_output(self):
        short = "short output"
        self.assertEqual(truncate_output(short, max_chars=100), short)
        long_text = "a" * 200
        truncated = truncate_output(long_text, max_chars=50, save_log=False)
        self.assertIn("truncated", truncated.lower())

    def test_process_carriage_returns(self):
        self.assertEqual(process_carriage_returns("foo\rbar\nbaz"), "bar\nbaz")
        self.assertEqual(process_carriage_returns(""), "")

    def test_process_carriage_returns_lines(self):
        lines = ["progress 1\rprogress 2", "done"]
        out, is_spinner = process_carriage_returns_lines(lines)
        self.assertIn("progress 2", out)
        self.assertIn("done", out)
        self.assertFalse(is_spinner)

    def test_is_spinner_line(self):
        self.assertTrue(is_spinner_line("-"))
        self.assertTrue(is_spinner_line(" | "))
        self.assertFalse(is_spinner_line("normal text"))

    def test_format_duration(self):
        self.assertEqual(format_duration(None), "")
        self.assertEqual(format_duration(0), "0s")
        self.assertEqual(format_duration(5.5), "5.5s")
        self.assertEqual(format_duration(65), "1m 05s")


class TestPaletteUtils(unittest.TestCase):
    def test_query_terminal_palette(self):
        with patch(
            "johnston.core.infrastructure.platform.terminal_theme.query_terminal_palette",
            return_value=("#000000", "#ffffff"),
        ):
            bg, fg = query_terminal_palette()
            self.assertEqual(bg, "#000000")
            self.assertEqual(fg, "#ffffff")

    def test_compute_adaptive_palette(self):
        palette = compute_adaptive_palette("#111111", "#eeeeee")
        self.assertIn("dark", palette)
        self.assertTrue(palette["dark"])
        self.assertIn("tcss_vars", palette)


class TestClipboardUtils(unittest.IsolatedAsyncioTestCase):
    async def test_copy_to_os_clipboard_async(self):
        with patch(
            "johnston.core.infrastructure.platform.platform_utils.copy_to_os_clipboard_async"
        ) as mock_copy:
            await copy_to_os_clipboard_async("test_text")
            mock_copy.assert_called_once_with("test_text")

    def test_get_clipboard_image_or_file(self):
        with patch(
            "johnston.core.infrastructure.platform.platform_utils.get_clipboard_image_or_file",
            return_value=("/tmp/test.png", None),
        ) as mock_get:
            path, img = get_clipboard_image_or_file()
            self.assertEqual(path, "/tmp/test.png")
            self.assertIsNone(img)
            mock_get.assert_called_once()
