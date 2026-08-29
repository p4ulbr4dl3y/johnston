"""Regression tests for right-aligned badge row formatting and the unified
subagent running predicate (row_format helper used by tasks/resume/rewind/
mcp/diff-sidebar lists)."""
import unittest
from unittest.mock import MagicMock

from rich.cells import cell_len
from rich.markup import escape
from rich.text import Text

from widgets.presentation.tool_display import is_subagent_running
from widgets.utils.row_format import (
    DIFF_SIDEBAR_ROW_WIDTH,
    MODAL_DEFAULT_ROW_WIDTH,
    MODAL_MEDIUM_ROW_WIDTH,
    MODAL_WIDE_ROW_WIDTH,
    display_width,
    ellipsize,
    format_badge_row,
    format_relative_time,
    option_list_row_width,
)


def visible_len(row: str) -> int:
    """Visible width of a rendered row: parse rich markup, measure cells."""
    return cell_len(Text.from_markup(row).plain)


class TestDisplayWidth(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(display_width("abc"), 3)

    def test_wide_chars_count_two(self):
        self.assertEqual(display_width("日本語"), 6)
        self.assertNotEqual(display_width("日本語"), len("日本語"))


class TestEllipsize(unittest.TestCase):
    def test_noop_when_fits(self):
        self.assertEqual(ellipsize("hello", 10), "hello")

    def test_truncates_with_ellipsis_within_budget(self):
        out = ellipsize("hello world", 8)
        self.assertTrue(out.endswith("..."))
        self.assertLessEqual(display_width(out), 8)

    def test_cell_aware_truncation_keeps_width(self):
        text = "日本語日本語日本語"
        out = ellipsize(text, 8)
        self.assertLessEqual(display_width(out), 8)
        self.assertTrue(out.endswith("..."))

    def test_zero_budget(self):
        self.assertEqual(ellipsize("abc", 0), "...")


class TestFormatBadgeRow(unittest.TestCase):
    def test_badge_flush_right_at_target_width(self):
        row = format_badge_row("Research codebase", "running • 12s", target_width=40)
        self.assertEqual(visible_len(row), 40)
        self.assertIn("[dim]running • 12s[/]", row)

    def test_min_gap_enforced_when_title_too_long(self):
        row = format_badge_row("x" * 100, "done", target_width=20)
        self.assertIn("...", row)
        # Title truncated to reserve space; row never shorter than min gap.
        self.assertGreaterEqual(visible_len(row) - 4, 12)  # 20 - 4 badge - gap slack

    def test_wide_char_title_still_aligns_badge(self):
        title = "研究コードベースの構造を調べる" * 2
        row = format_badge_row(title, "done", target_width=50)
        self.assertEqual(visible_len(row), 50)

    def test_empty_badge_plain_row(self):
        row = format_badge_row("plain [title]", "")
        self.assertEqual(row, f"{escape('plain [title]')}")

    def test_prefix_included_in_math(self):
        row = format_badge_row("sess one", "5 steps", target_width=30, prefix="● ")
        self.assertEqual(visible_len(row), 30)
        self.assertTrue(row.startswith("● sess one"))

    def test_prefix_with_rich_markup_keeps_badge_aligned(self):
        prefix = "[dim]└─ [/]"
        row = format_badge_row("Forked session title", "14 steps", target_width=60, prefix=prefix)
        self.assertEqual(visible_len(row), 60)
        self.assertIn("14 steps", row)

    def test_whitespace_collapsed_and_escaped(self):
        row = format_badge_row("multi\nline\rtab  x [br]", "done", target_width=60)
        self.assertNotIn("\n", row)
        self.assertNotIn("\r", row)
        self.assertIn(escape("x [br]"), row)


class TestIsSubagentRunning(unittest.TestCase):
    def _sess(self, status=None, is_running=None):
        class S:
            pass

        s = S()
        if status is not None:
            s.status = status
        if is_running is not None:
            s.is_running = is_running
        return s

    def test_running_and_active_statuses(self):
        self.assertTrue(is_subagent_running(self._sess(status="running")))
        self.assertTrue(is_subagent_running(self._sess(status="RUNNING")))
        # ACTIVE sessions (created, stream not started yet) count as running.
        self.assertTrue(is_subagent_running(self._sess(status="active")))
        self.assertTrue(is_subagent_running(self._sess(status="Active")))

    def test_terminal_statuses(self):
        for st in ("completed", "cancelled", "error"):
            self.assertFalse(is_subagent_running(self._sess(status=st)))

    def test_is_running_attribute_fallback(self):
        self.assertTrue(is_subagent_running(self._sess(is_running=True)))
        self.assertFalse(is_subagent_running(self._sess(is_running=False)))

    def test_missing_status_not_running(self):
        self.assertFalse(is_subagent_running(object()))


class TestDiffSidebarWidthConstant(unittest.TestCase):
    def test_constant_matches_css_geometry(self):
        # app.tcss: #diff-sidebar width 34 - border-right 1 - option padding 2x1.
        self.assertEqual(DIFF_SIDEBAR_ROW_WIDTH, 31)


class TestDialogWidthConstants(unittest.TestCase):
    def test_modal_widths_account_for_option_padding(self):
        # Modal OptionList options render with Textual default padding 0 1;
        # rows wider than the remaining text area get ellipsized by CSS.
        self.assertEqual(MODAL_WIDE_ROW_WIDTH, 96)  # 104 - 4 - 2 - 2
        self.assertEqual(MODAL_MEDIUM_ROW_WIDTH, 78)  # 86 - 4 - 2 - 2
        self.assertEqual(MODAL_DEFAULT_ROW_WIDTH, 70)  # 78 - 4 - 2 - 2


class TestOptionListRowWidth(unittest.TestCase):
    def test_mounted_widget_subtracts_option_padding(self):
        widget = MagicMock()
        widget.size.width = 60
        # 60 - 2 = 58
        self.assertEqual(option_list_row_width(widget, default=78), 58)

    def test_mounted_widget_clamps_at_minimum_20(self):
        widget = MagicMock()
        widget.size.width = 21
        # max(20, 21 - 2) = 20
        self.assertEqual(option_list_row_width(widget, default=78), 20)

    def test_unmounted_widget_clamps_against_screen_width(self):
        widget = MagicMock()
        widget.size.width = 0
        app = MagicMock()
        app.size.width = 80
        widget.app = app
        # 80 * 0.9 - 8 = 64
        self.assertEqual(option_list_row_width(widget, default=78), 64)

    def test_unmounted_widget_wide_screen_uses_default(self):
        widget = MagicMock()
        widget.size.width = 0
        app = MagicMock()
        app.size.width = 120
        widget.app = app
        # 120 * 0.9 - 8 = 100 > 78 -> returns 78
        self.assertEqual(option_list_row_width(widget, default=78), 78)

    def test_unmounted_no_size_info_clamps_to_default_terminal(self):
        widget = object()
        # Default terminal is 80 -> cap is 64; 78 clamped to 64
        self.assertEqual(option_list_row_width(widget, default=78), 64)
        # Small default (e.g. 50 < 64) remains 50
        self.assertEqual(option_list_row_width(widget, default=50), 50)


class TestFormatRelativeTime(unittest.TestCase):
    def test_none_or_invalid(self):
        self.assertEqual(format_relative_time(None), "")
        self.assertEqual(format_relative_time(0), "")
        self.assertEqual(format_relative_time(-100), "")
        self.assertEqual(format_relative_time("invalid"), "")

    def test_just_now(self):
        now = 1000.0
        self.assertEqual(format_relative_time(1000.0, now=now), "just now")
        self.assertEqual(format_relative_time(950.0, now=now), "just now")
        self.assertEqual(format_relative_time(1010.0, now=now), "just now")

    def test_minutes(self):
        now = 10000.0
        self.assertEqual(format_relative_time(now - 60, now=now), "1m ago")
        self.assertEqual(format_relative_time(now - 3599, now=now), "59m ago")

    def test_hours(self):
        now = 100000.0
        self.assertEqual(format_relative_time(now - 3600, now=now), "1h ago")
        self.assertEqual(format_relative_time(now - 86399, now=now), "23h ago")

    def test_days(self):
        now = 1000000.0
        self.assertEqual(format_relative_time(now - 86400, now=now), "1d ago")
        self.assertEqual(format_relative_time(now - 86400 * 6, now=now), "6d ago")

    def test_weeks(self):
        now = 10000000.0
        self.assertEqual(format_relative_time(now - 86400 * 7, now=now), "1w ago")
        self.assertEqual(format_relative_time(now - 86400 * 25, now=now), "3w ago")

    def test_months(self):
        now = 100000000.0
        self.assertEqual(format_relative_time(now - 86400 * 30, now=now), "1mo ago")
        self.assertEqual(format_relative_time(now - 86400 * 300, now=now), "10mo ago")

    def test_years(self):
        now = 1000000000.0
        self.assertEqual(format_relative_time(now - 86400 * 365, now=now), "1y ago")
        self.assertEqual(format_relative_time(now - 86400 * 365 * 3, now=now), "3y ago")


if __name__ == "__main__":
    unittest.main()


