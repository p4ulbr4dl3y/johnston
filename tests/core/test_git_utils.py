"""Coverage-focused tests for core/git_utils.py."""

import subprocess
import unittest
from unittest.mock import patch

from core.infrastructure.runtime.git_utils import make_git_diff, run_git


class TestRunGit(unittest.TestCase):
    def test_successful_run(self):
        with patch("core.infrastructure.runtime.git_utils.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "status"], returncode=0, stdout="clean", stderr=""
            )
            res = run_git(["status"], cwd="/tmp", timeout=5)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "clean")
        mock_run.assert_called_once_with(
            ["git", "status"], cwd="/tmp", capture_output=True, text=True, encoding="utf-8", env=None, timeout=5
        )

    def test_timeout_returns_124(self):
        with patch(
            "core.infrastructure.runtime.git_utils.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git", "fetch"], timeout=1),
        ):
            res = run_git(["fetch"], timeout=1)
        self.assertEqual(res.returncode, 124)
        self.assertIn("timeout", res.stderr)

    def test_other_exception_returns_1(self):
        with patch("core.infrastructure.runtime.git_utils.subprocess.run", side_effect=OSError("git missing")):
            res = run_git(["rev-parse", "HEAD"])
        self.assertEqual(res.returncode, 1)
        self.assertEqual(res.stderr, "git missing")

    def test_env_and_no_timeout_passthrough(self):
        with patch("core.infrastructure.runtime.git_utils.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "log"], returncode=0, stdout="", stderr=""
            )
            run_git(["log"], env={"GIT_CONFIG": "x"})
        kwargs = mock_run.call_args.kwargs
        self.assertEqual(kwargs["env"], {"GIT_CONFIG": "x"})
        self.assertIsNone(kwargs["timeout"])


class TestMakeGitDiff(unittest.TestCase):
    def test_identical_returns_empty(self):
        self.assertEqual(make_git_diff("a\nb\n", "a\nb\n"), "")

    def test_both_empty_returns_empty(self):
        self.assertEqual(make_git_diff("", ""), "")

    def test_single_line_change(self):
        d = make_git_diff("a", "b", fromfile="old", tofile="new")
        self.assertIn("--- old\n+++ new", d)
        self.assertIn("-a", d)
        self.assertIn("+b", d)

    def test_relabels_to_caller_paths(self):
        d = make_git_diff("a\nb\n", "a\nc\n", fromfile="a/foo.py", tofile="b/foo.py")
        self.assertIn("+++ b/foo.py", d)
        self.assertNotIn("tmp", d)

    def test_list_input(self):
        d = make_git_diff(["a", "b"], ["a", "c"])
        self.assertIn("-b", d)
        self.assertIn("+c", d)

    def test_new_file_add(self):
        d = make_git_diff("", "x\ny\n", fromfile="old", tofile="new")
        self.assertIn("@@ -0,0 +1,2 @@", d)
        self.assertIn("+x", d)
        self.assertIn("+y", d)

    def test_fallback_when_git_unavailable(self):
        with patch("core.infrastructure.runtime.git_utils.run_git", side_effect=OSError("no git")):
            d = make_git_diff("a\nb\n", "a\nc\n", fromfile="old", tofile="new")
        self.assertIn("--- old\n+++ new", d)
        self.assertIn("-b", d)
        self.assertIn("+c", d)

    def test_fallback_when_git_errors(self):
        with patch(
            "core.infrastructure.runtime.git_utils.run_git",
            return_value=subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="boom"),
        ):
            d = make_git_diff("a\nb\n", "a\nc\n", fromfile="old", tofile="new")
        self.assertIn("-b", d)
        self.assertIn("+c", d)

    def test_fallback_when_git_surfaces_missing_binary(self):
        # git binary missing yields rc=1 with empty stdout (caught inside run_git).
        with patch(
            "core.infrastructure.runtime.git_utils.run_git",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="[Errno 2] No such file or directory: 'git'"
            ),
        ):
            d = make_git_diff("a\nb\n", "a\nc\n", fromfile="old", tofile="new")
        self.assertIn("--- old\n+++ new", d)
        self.assertIn("-b", d)
        self.assertIn("+c", d)

    def test_identical_does_not_call_git(self):
        with patch("core.infrastructure.runtime.git_utils.run_git") as m:
            make_git_diff("a\n", "a\n")
        m.assert_not_called()

    def test_trailing_newline_added_detected(self):
        d = make_git_diff("a\nb", "a\nb\n", fromfile="old", tofile="new")
        self.assertNotEqual(d, "")
        self.assertIn("+b\n", d)

    def test_trailing_newline_removed_detected(self):
        d = make_git_diff("a\nb\n", "a\nb", fromfile="old", tofile="new")
        self.assertNotEqual(d, "")
        self.assertIn("-b\n", d)

    def test_trailing_newline_equal_returns_empty(self):
        self.assertEqual(make_git_diff("a\nb\n", "a\nb\n"), "")


class TestGitContextUtils(unittest.TestCase):
    def test_is_git_repository_true(self):
        from core.infrastructure.runtime.git_utils import is_git_repository

        with patch("core.infrastructure.runtime.git_utils.run_git") as mock_git:
            mock_git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="true\n", stderr=""
            )
            self.assertTrue(is_git_repository("/tmp"))

    def test_is_git_repository_false(self):
        from core.infrastructure.runtime.git_utils import is_git_repository

        with patch("core.infrastructure.runtime.git_utils.run_git") as mock_git:
            mock_git.return_value = subprocess.CompletedProcess(
                args=[], returncode=128, stdout="", stderr="fatal"
            )
            self.assertFalse(is_git_repository("/tmp"))

    def test_format_git_branch_info_named_branch(self):
        from core.infrastructure.runtime.git_utils import format_git_branch_info

        with patch("core.infrastructure.runtime.git_utils.run_git") as mock_git:
            mock_git.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="main\n", stderr=""
            )
            self.assertEqual(format_git_branch_info("/tmp"), "main")

    def test_format_git_branch_info_detached_head(self):
        from core.infrastructure.runtime.git_utils import format_git_branch_info

        def side_effect(args, **kwargs):
            if "--show-current" in args:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
            if "--short" in args:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc1234\n", stderr="")
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")

        with patch("core.infrastructure.runtime.git_utils.run_git", side_effect=side_effect):
            self.assertEqual(format_git_branch_info("/tmp"), "detached HEAD (abc1234)")

    def test_format_git_branch_info_not_repo(self):
        from core.infrastructure.runtime.git_utils import format_git_branch_info

        with patch("core.infrastructure.runtime.git_utils.run_git") as mock_git:
            mock_git.return_value = subprocess.CompletedProcess(
                args=[], returncode=128, stdout="", stderr="fatal"
            )
            self.assertEqual(format_git_branch_info("/tmp"), "")


if __name__ == "__main__":
    unittest.main()
