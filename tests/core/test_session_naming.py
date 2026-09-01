"""Unit tests for the canonical fork-naming policy."""

import unittest

from core.domain.policies.session_naming import (
    FORK_BASE_MAX_LEN,
    build_fork_title,
    fork_marker,
    strip_fork_suffix,
)


class TestStripForkSuffix(unittest.TestCase):
    def test_plain_title_untouched(self):
        self.assertEqual(strip_fork_suffix("Fix login button"), "Fix login button")

    def test_removes_numbered_and_plain_markers(self):
        self.assertEqual(strip_fork_suffix("Fix login (fork)"), "Fix login")
        self.assertEqual(strip_fork_suffix("Fix login (fork 3)"), "Fix login")

    def test_marker_is_case_insensitive(self):
        self.assertEqual(strip_fork_suffix("Fix login (Fork 2)"), "Fix login")

    def test_only_trailing_marker_is_removed(self):
        self.assertEqual(strip_fork_suffix("(fork) Fix login (fork)"), "(fork) Fix login")

    def test_empty_input(self):
        self.assertEqual(strip_fork_suffix(""), "")
        self.assertEqual(strip_fork_suffix(None), "")


class TestForkMarker(unittest.TestCase):
    def test_returns_marker_with_leading_space(self):
        self.assertEqual(fork_marker("Fix login (fork)"), " (fork)")
        self.assertEqual(fork_marker("Fix login (fork 2)"), " (fork 2)")

    def test_no_marker(self):
        self.assertEqual(fork_marker("Fix login"), "")
        self.assertEqual(fork_marker(""), "")


class TestBuildForkTitle(unittest.TestCase):
    def test_first_fork_has_no_number(self):
        self.assertEqual(build_fork_title("Fix login", 1), "Fix login (fork)")

    def test_later_forks_are_numbered(self):
        self.assertEqual(build_fork_title("Fix login", 2), "Fix login (fork 2)")
        self.assertEqual(build_fork_title("Fix login", 17), "Fix login (fork 17)")

    def test_marker_does_not_accumulate(self):
        self.assertEqual(build_fork_title("Fix login (fork 4)", 1), "Fix login (fork)")
        self.assertEqual(build_fork_title("Fix login (fork 4)", 3), "Fix login (fork 3)")

    def test_empty_base_falls_back_to_untitled(self):
        self.assertEqual(build_fork_title("", 1), "Untitled (fork)")
        self.assertEqual(build_fork_title("   (fork)", 2), "Untitled (fork 2)")

    def test_non_ascii_base(self):
        self.assertEqual(build_fork_title("Парсинг логов Nginx", 2), "Парсинг логов Nginx (fork 2)")

    def test_title_fits_resume_row_budget(self):
        base = "a" * FORK_BASE_MAX_LEN
        title = build_fork_title(base, 12)
        self.assertLessEqual(len(title), FORK_BASE_MAX_LEN + len(" (fork 12)"))
        self.assertTrue(title.endswith("(fork 12)"))

    def test_overlong_base_is_truncated_to_budget(self):
        title = build_fork_title("b" * 500, 1)
        self.assertLessEqual(len(title), FORK_BASE_MAX_LEN + len(" (fork)"))
        self.assertTrue(title.endswith("(fork)"))

    def test_overlong_base_cut_at_word_boundary(self):
        base = "fix the parser crash " + "y" * 100
        title = build_fork_title(base, 2)
        base_part = title[: -len(" (fork 2)")]
        self.assertLessEqual(len(base_part), FORK_BASE_MAX_LEN)
        self.assertTrue(base_part.startswith("fix the parser crash"))

    def test_overlong_base_without_spaces_keeps_full_cut(self):
        title = build_fork_title("z" * 100, 3)
        self.assertEqual(title, "z" * FORK_BASE_MAX_LEN + " (fork 3)")


if __name__ == "__main__":
    unittest.main()
