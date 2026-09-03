"""Incremental shell-stream flush tests.

Covers the perf fix in ``widgets/chat_toolcall.py::_flush_shell_update``:

- ``result_text`` stays byte-identical to the legacy full-buffer computation
  ``process_carriage_returns(clean_bash_output(buf))`` even when ``\\r``
  sequences, spinner lines and truncation banners are split across flushes;
- each flush only re-processes the delta (boundary-safe ``\\r`` handling via
  the carried partial line), never the whole buffer;
- truncation at ``_RAW_BASH_LIMIT`` re-syncs the incremental state;
- unchanged results skip the re-render.
"""

import unittest
from unittest.mock import patch

from core.infrastructure.tasks.output import process_carriage_returns
from widgets.chat_toolcall import ToolCallWidget, _bash_safe_boundary, format_truncation_for_ui


def legacy_result(widget) -> str:
    """The pre-fix computation: full buffer cleaned + carriage returns."""
    return process_carriage_returns(widget._clean_bash_output(widget._raw_bash_buffer))


class TestBashSafeBoundary(unittest.TestCase):
    def test_partial_line_is_carried(self):
        # Committed prefix must stop at the last newline; "abc\rde" stays raw.
        self.assertEqual(_bash_safe_boundary("abc\rde"), 0)
        self.assertEqual(_bash_safe_boundary("a\nb\nc\rde"), 4)
        self.assertEqual(_bash_safe_boundary("a\nb\n"), 4)
        self.assertEqual(_bash_safe_boundary(""), 0)

    def test_unterminated_banner_is_carried(self):
        # A banner without "]" must not be committed even if a newline follows:
        # nothing is committed (boundary 0) because the partial line before the
        # banner start cannot be split off safely.
        self.assertEqual(_bash_safe_boundary("line1 [Output truncated\nfoo"), 0)
        self.assertEqual(_bash_safe_boundary("line1 [Output truncated\nfoo\nmore"), 0)

    def test_completed_banner_is_committed(self):
        examine = "line1 [Output truncated: 5 chars]\nfoo\n"
        self.assertEqual(_bash_safe_boundary(examine), len(examine))

    def test_lowercase_truncated_banner_is_carried(self):
        # "...\n" is an open banner start only while "]" is missing; here the
        # banner closes before the last newline, so only the trailing partial
        # line ("rest") is carried.
        self.assertEqual(_bash_safe_boundary("...\n[truncated | log /x]\nrest"), 25)
        # Once closed, the whole region commits.
        self.assertEqual(_bash_safe_boundary("...\n[truncated | log /x]\n"), 25)


class TestIncrementalFlushMatchesLegacy(unittest.TestCase):
    def _stream(self) -> list[str]:
        """Long-ish stream with \r sequences split across chunk boundaries,
        spinner lines, blank lines and a truncation banner."""
        return [
            "part1\rpart2\rpart3\n",
            "line2\r",
            "line2-tail\n",
            "\n",
            "-\n",
            "/\n",
            "\\\n",
            "progress 10%\r",
            "progress 20%\r",
            "progress 99%\n",
            "  leading and trailing  \n",
            "a\rb\r",
            "c\r\nd\r\n",
            "e",
            "f\rg\n",
            "... [Output truncated: showing last 4000 chars (lines 1-100 of 500). ",
            "Full log: /path/to.log. Use read to inspect.]\n",
            "final line\n",
        ]

    def test_result_text_equals_legacy_after_every_chunk(self):
        widget = ToolCallWidget("shell", "cmd")
        widget.is_expanded = False
        for chunk in self._stream():
            widget.append_shell_output(chunk)
            self.assertEqual(widget.result_text, legacy_result(widget))
        # Final buffer consumed up to the last byte.
        self.assertEqual(widget._bash_processed_len, len(widget._raw_bash_buffer))
        self.assertEqual(widget.result_text, legacy_result(widget))

    def test_cr_sequences_split_across_flushes(self):
        widget = ToolCallWidget("shell", "cmd")
        for chunk in ["abc\r", "def\n", "x\r", "y\r", "z\n", "q", "r\r", "s\n"]:
            widget.append_shell_output(chunk)
            self.assertEqual(widget.result_text, legacy_result(widget))
        self.assertEqual(widget.result_text, "def\nz\ns")

    def test_spinner_lines_across_flushes(self):
        widget = ToolCallWidget("shell", "cmd")
        for chunk in ["-\n", "/\n", "\\\n", "|\n"]:
            widget.append_shell_output(chunk)
            self.assertEqual(widget.result_text, legacy_result(widget))
        # Consecutive spinner lines collapse into the last one.
        self.assertEqual(widget.result_text, "|")

    def test_leading_whitespace_stripped_only_once(self):
        widget = ToolCallWidget("shell", "cmd")
        for chunk in ["\n  ", "lead\n", "tail  \n"]:
            widget.append_shell_output(chunk)
            self.assertEqual(widget.result_text, legacy_result(widget))

    def test_randomized_chunked_stream(self):
        import random

        rng = random.Random(1234)
        base = (
            "build start\r\nstep a\rstep b\n"
            "10%\r20%\r30%\r40%\n"
            "-\n\\\n/\n|\n"
            "plain line with text\n"
            "[Ok]\n\r\n"
            "some[Output truncated: showing recent output]\n"
            "[Truncated: x | y]\n"
        )
        widget = ToolCallWidget("shell", "cmd")
        for _ in range(200):
            pos = rng.randint(0, len(base))
            chunk = base[pos:] if rng.random() < 0.5 else base[:pos]
            if rng.random() < 0.7:
                # Most chunks are small slices so \r boundaries get split hard.
                chunk = chunk[: rng.randint(1, 8)]
            widget.append_shell_output(chunk)
            self.assertEqual(widget.result_text, legacy_result(widget))
        self.assertEqual(widget.result_text, legacy_result(widget))

    def test_per_flush_work_is_bounded_by_delta(self):
        widget = ToolCallWidget("shell", "cmd")
        widget.is_expanded = False
        stream = self._stream()
        total = sum(len(c) for c in stream)
        self.assertGreater(total, 200)  # sanity: it's a real stream

        calls: list[int] = []

        def spy(text, **kwargs):
            calls.append(len(text))
            return format_truncation_for_ui(text, **kwargs)

        with patch("widgets.chat_toolcall.format_truncation_for_ui", side_effect=spy):
            for chunk in stream:
                widget.append_shell_output(chunk)
        self.assertTrue(calls)
        # Each flush only cleaned the delta (plus at most the carried partial
        # line), never the whole accumulated buffer.
        self.assertLessEqual(max(calls), 256)
        self.assertLess(max(calls), total)
        self.assertEqual(widget._bash_processed_len, len(widget._raw_bash_buffer))

    def test_truncation_marker_resyncs_incremental_state(self):
        widget = ToolCallWidget("shell", "cmd")
        limit = widget._RAW_BASH_LIMIT
        # Stream well past the limit in a few chunks.
        for i in range((limit // 50_000) + 3):
            widget.append_shell_output(f"line {i}: " + "x" * 49_900 + "\n")
        buf = widget._raw_bash_buffer
        self.assertLessEqual(len(buf), len(widget._RAW_BASH_TRUNC) + limit)
        self.assertIn(widget._RAW_BASH_TRUNC, buf)
        self.assertEqual(widget._bash_processed_len, len(buf))
        self.assertEqual(widget.result_text, legacy_result(widget))
        # The stream continues incrementally after the resync.
        widget.append_shell_output("tail line\n")
        self.assertEqual(widget._bash_processed_len, len(widget._raw_bash_buffer))
        self.assertEqual(widget.result_text, legacy_result(widget))

    def test_unchanged_result_skips_render(self):
        widget = ToolCallWidget("shell", "cmd")
        widget.is_expanded = True
        widget.append_shell_output("hello\r")
        with patch.object(widget, "render_content") as render_mock, patch.object(
            widget, "_scroll_if_needed"
        ) as scroll_mock:
            widget._flush_shell_update()  # no new bytes -> result unchanged
            render_mock.assert_not_called()
            scroll_mock.assert_not_called()
        self.assertEqual(widget.result_text, "hello")
        # New bytes still render.
        with patch.object(widget, "render_content") as render_mock:
            widget.append_shell_output(" world\n")
            render_mock.assert_called_once()
        self.assertEqual(widget.result_text, legacy_result(widget))


if __name__ == "__main__":
    unittest.main()
