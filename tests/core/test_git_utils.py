"""Coverage-focused tests for core/git_utils.py."""

import subprocess
import unittest
from unittest.mock import patch

from core.git_utils import run_git


class TestRunGit(unittest.TestCase):
    def test_successful_run(self):
        with patch("core.git_utils.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "status"], returncode=0, stdout="clean", stderr=""
            )
            res = run_git(["status"], cwd="/tmp", timeout=5)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "clean")
        mock_run.assert_called_once_with(
            ["git", "status"], cwd="/tmp", capture_output=True, text=True, env=None, timeout=5
        )

    def test_timeout_returns_124(self):
        with patch(
            "core.git_utils.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git", "fetch"], timeout=1),
        ):
            res = run_git(["fetch"], timeout=1)
        self.assertEqual(res.returncode, 124)
        self.assertIn("timeout", res.stderr)

    def test_other_exception_returns_1(self):
        with patch("core.git_utils.subprocess.run", side_effect=OSError("git missing")):
            res = run_git(["rev-parse", "HEAD"])
        self.assertEqual(res.returncode, 1)
        self.assertEqual(res.stderr, "git missing")

    def test_env_and_no_timeout_passthrough(self):
        with patch("core.git_utils.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "log"], returncode=0, stdout="", stderr=""
            )
            run_git(["log"], env={"GIT_CONFIG": "x"})
        kwargs = mock_run.call_args.kwargs
        self.assertEqual(kwargs["env"], {"GIT_CONFIG": "x"})
        self.assertIsNone(kwargs["timeout"])


if __name__ == "__main__":
    unittest.main()
