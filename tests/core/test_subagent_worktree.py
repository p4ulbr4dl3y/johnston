import os
import subprocess
import tempfile
import unittest

from core.subagent_worktree import SubagentWorktreeManager


class TestSubagentWorktreeManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = self.temp_dir.name

        # Init git repo
        subprocess.run(["git", "init"], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=self.repo_dir, capture_output=True, text=True
        )

        dummy_file = os.path.join(self.repo_dir, "README.md")
        with open(dummy_file, "w", encoding="utf-8") as f:
            f.write("# Test Repo\n")

        subprocess.run(["git", "add", "."], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.repo_dir, capture_output=True, text=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_is_git_repo(self):
        self.assertTrue(SubagentWorktreeManager.is_git_repo(self.repo_dir))
        self.assertFalse(SubagentWorktreeManager.is_git_repo("/non/existent/path"))

    def test_create_and_cleanup_worktree_with_changes(self):
        session_id = "test-wt-12345"
        wt_path, branch_name = SubagentWorktreeManager.create_worktree(self.repo_dir, session_id)

        self.assertIsNotNone(wt_path)
        self.assertIsNotNone(branch_name)
        self.assertTrue(os.path.exists(wt_path))
        self.assertEqual(branch_name, f"subagent-{session_id}")

        # Modify file inside worktree
        wt_file = os.path.join(wt_path, "README.md")
        with open(wt_file, "a", encoding="utf-8") as f:
            f.write("Worktree edit\n")

        diff_summary, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(
            self.repo_dir, wt_path, branch_name
        )
        self.assertTrue(has_changes)
        self.assertIn("Worktree edit", diff_summary)

        # Cleanup keeping branch
        SubagentWorktreeManager.cleanup_worktree(self.repo_dir, wt_path, branch_name, keep_branch=True)
        self.assertFalse(os.path.exists(wt_path))

        # Check branch exists in repo
        res = subprocess.run(
            ["git", "branch", "--list", branch_name], cwd=self.repo_dir, capture_output=True, text=True
        )
        self.assertIn(branch_name, res.stdout)

        # Clean up branch manually for test
        subprocess.run(["git", "branch", "-D", branch_name], cwd=self.repo_dir, capture_output=True, text=True)

    def test_cleanup_worktree_no_changes_deletes_branch(self):
        session_id = "test-wt-no-changes"
        wt_path, branch_name = SubagentWorktreeManager.create_worktree(self.repo_dir, session_id)

        diff_summary, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(
            self.repo_dir, wt_path, branch_name
        )
        self.assertFalse(has_changes)
        self.assertEqual(diff_summary, "")

        # Cleanup without keeping branch
        SubagentWorktreeManager.cleanup_worktree(self.repo_dir, wt_path, branch_name, keep_branch=False)
        self.assertFalse(os.path.exists(wt_path))

        res = subprocess.run(
            ["git", "branch", "--list", branch_name], cwd=self.repo_dir, capture_output=True, text=True
        )
        self.assertNotIn(branch_name, res.stdout)

    def test_worktree_manual_commits_by_subagent_detected(self):
        """Verify that if subagent manually runs git commit (leaving git status empty), get_worktree_diff_summary still detects changes against base commit."""
        session_id = "manual-commit-task"
        wt_path, branch_name = SubagentWorktreeManager.create_worktree(self.repo_dir, session_id)

        # Subagent manually creates file and commits
        manual_file = os.path.join(wt_path, "manual.txt")
        with open(manual_file, "w", encoding="utf-8") as f:
            f.write("Manual commit contents\n")

        subprocess.run(["git", "add", "."], cwd=wt_path, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "Subagent manual commit"], cwd=wt_path, capture_output=True, text=True)

        # Git status --short is now empty, but branch has commits relative to parent repo base_sha
        diff_summary, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(
            self.repo_dir, wt_path, branch_name
        )
        self.assertTrue(has_changes)
        self.assertIn("manual.txt", diff_summary)
        self.assertIn("Manual commit contents", diff_summary)

        # Cleanup preserving branch
        SubagentWorktreeManager.cleanup_worktree(self.repo_dir, wt_path, branch_name, keep_branch=has_changes)

        # Merge branch into parent repo
        merge_res = subprocess.run(["git", "merge", branch_name], cwd=self.repo_dir, capture_output=True, text=True)
        self.assertEqual(merge_res.returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(self.repo_dir, "manual.txt")))

    def test_worktree_branch_git_merge_integration(self):
        """Full end-to-end verification: create worktree, write files, remove worktree, git merge branch."""
        session_id = "e2e-merge-task"
        wt_path, branch_name = SubagentWorktreeManager.create_worktree(self.repo_dir, session_id)

        # Subagent creates new file and edits existing file inside worktree
        new_file = os.path.join(wt_path, "feature.py")
        with open(new_file, "w", encoding="utf-8") as f:
            f.write("def feature(): return 'ok'\n")

        readme_file = os.path.join(wt_path, "README.md")
        with open(readme_file, "a", encoding="utf-8") as f:
            f.write("Updated README\n")

        # Auto-commit and get diff
        diff_summary, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(
            self.repo_dir, wt_path, branch_name
        )
        self.assertTrue(has_changes)
        self.assertIn("feature.py", diff_summary)
        self.assertIn("Updated README", diff_summary)

        # Cleanup worktree directory, preserving branch
        SubagentWorktreeManager.cleanup_worktree(self.repo_dir, wt_path, branch_name, keep_branch=has_changes)
        self.assertFalse(os.path.exists(wt_path))

        # Parent repo performs git merge branch_name
        merge_res = subprocess.run(["git", "merge", branch_name], cwd=self.repo_dir, capture_output=True, text=True)
        self.assertEqual(merge_res.returncode, 0)

        # Verify merged files exist in parent repo
        merged_feature = os.path.join(self.repo_dir, "feature.py")
        self.assertTrue(os.path.exists(merged_feature))
        with open(merged_feature, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "def feature(): return 'ok'\n")

        with open(os.path.join(self.repo_dir, "README.md"), "r", encoding="utf-8") as f:
            self.assertIn("Updated README", f.read())


class TestSubagentWorktreeEdgeCases(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = self.temp_dir.name

        subprocess.run(["git", "init"], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=self.repo_dir, capture_output=True, text=True
        )

        dummy_file = os.path.join(self.repo_dir, "README.md")
        with open(dummy_file, "w", encoding="utf-8") as f:
            f.write("# Test Repo\n")

        subprocess.run(["git", "add", "."], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.repo_dir, capture_output=True, text=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_worktree_non_git_repo(self):
        non_git_dir = tempfile.TemporaryDirectory()
        try:
            wt_path, branch_name = SubagentWorktreeManager.create_worktree(non_git_dir.name, "subagent-x")
        finally:
            non_git_dir.cleanup()
        self.assertIsNone(wt_path)
        self.assertIsNone(branch_name)

    def test_create_worktree_git_add_failure(self):
        from unittest.mock import patch

        with (
            patch.object(SubagentWorktreeManager, "is_git_repo", return_value=True),
            patch(
                "core.subagent_worktree.run_git",
                return_value=subprocess.CompletedProcess([], returncode=128, stdout="", stderr="err"),
            ),
        ):
            wt_path, branch_name = SubagentWorktreeManager.create_worktree(self.repo_dir, "subagent-x")
        self.assertIsNone(wt_path)
        self.assertIsNone(branch_name)

    def test_attach_worktree_non_git(self):
        non_git = os.path.join(self.temp_dir.name, "not-a-repo")
        os.makedirs(non_git, exist_ok=True)
        self.assertIsNone(SubagentWorktreeManager.attach_worktree(non_git, "s1", "branch-x"))

    def test_attach_worktree_existing_path_returns_it(self):
        from core.config import WORKTREES_DIR

        wt_path = os.path.join(WORKTREES_DIR, "attach-existing")
        os.makedirs(wt_path, exist_ok=True)
        try:
            result = SubagentWorktreeManager.attach_worktree(self.repo_dir, "attach-existing", "branch-x")
            self.assertEqual(result, wt_path)
        finally:
            import shutil

            shutil.rmtree(wt_path, ignore_errors=True)

    def test_attach_worktree_add_failure(self):
        from unittest.mock import patch

        with (
            patch.object(SubagentWorktreeManager, "is_git_repo", return_value=True),
            patch(
                "core.subagent_worktree.run_git",
                return_value=subprocess.CompletedProcess([], returncode=128, stdout="", stderr="err"),
            ),
        ):
            result = SubagentWorktreeManager.attach_worktree(self.repo_dir, "attach-new", "branch-x")
        self.assertIsNone(result)

    def test_attach_worktree_success(self):
        from unittest.mock import patch

        from core.config import WORKTREES_DIR

        wt_path = os.path.join(WORKTREES_DIR, "attach-ok")
        os.makedirs(wt_path, exist_ok=True)
        try:
            with (
                patch.object(SubagentWorktreeManager, "is_git_repo", return_value=True),
                patch(
                    "core.subagent_worktree.run_git",
                    return_value=subprocess.CompletedProcess([], returncode=0, stdout="", stderr=""),
                ),
            ):
                result = SubagentWorktreeManager.attach_worktree(self.repo_dir, "attach-ok", "branch-x")
            self.assertEqual(result, wt_path)
        finally:
            import shutil

            shutil.rmtree(wt_path, ignore_errors=True)

    def test_get_worktree_diff_summary_missing_path(self):
        diff_summary, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(
            self.repo_dir, os.path.join(self.temp_dir.name, "missing"), "branch-x"
        )
        self.assertEqual(diff_summary, "")
        self.assertFalse(has_changes)

    def test_diff_truncated_at_4000(self):
        from unittest.mock import patch

        def fake_run(args, **kwargs):
            if args and args[0] == "status":
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if args and args[0] == "rev-parse":
                return subprocess.CompletedProcess(args, 0, stdout="abc123", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="x" * 5000, stderr="")

        with (
            patch.object(SubagentWorktreeManager, "is_git_repo", return_value=True),
            patch("core.subagent_worktree.run_git", side_effect=fake_run),
        ):
            diff_summary, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(
                self.repo_dir, self.repo_dir, "branch-x"
            )
        self.assertTrue(has_changes)
        self.assertIn("... [diff truncated]", diff_summary)
        self.assertLessEqual(len(diff_summary), 4200)

    def test_get_worktree_diff_summary_exception(self):
        from unittest.mock import patch

        with patch("core.subagent_worktree.run_git", side_effect=Exception("boom")):
            diff_summary, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(
                self.repo_dir, self.repo_dir, "branch-x"
            )
        self.assertEqual(diff_summary, "")
        self.assertFalse(has_changes)

    def test_cleanup_worktree_rmtree_error_ignored(self):
        from unittest.mock import patch

        wt_path = os.path.join(self.temp_dir.name, "wt-cleanup")
        os.makedirs(wt_path, exist_ok=True)
        with (
            patch.object(SubagentWorktreeManager, "is_git_repo", return_value=False),
            patch("shutil.rmtree", side_effect=OSError("boom")),
        ):
            SubagentWorktreeManager.cleanup_worktree(self.repo_dir, wt_path, "branch-x")  # must not raise
        self.assertTrue(os.path.exists(wt_path))
        os.rmdir(wt_path)

    def test_append_worktree_diff_to_acc_no_worktree(self):
        acc = [""]
        wt, branch = SubagentWorktreeManager.append_worktree_diff_to_acc(self.repo_dir, None, None, acc)
        self.assertEqual((wt, branch), (None, None))
        self.assertEqual(acc[0], "")

    def test_append_worktree_diff_to_acc_with_changes(self):
        from unittest.mock import patch

        wt_path = os.path.join(self.temp_dir.name, "wt-append")
        os.makedirs(wt_path, exist_ok=True)
        acc = [""]
        with (
            patch.object(SubagentWorktreeManager, "get_worktree_diff_summary", return_value=("Some diff", True)),
            patch.object(SubagentWorktreeManager, "cleanup_worktree") as mock_cleanup,
        ):
            wt, branch = SubagentWorktreeManager.append_worktree_diff_to_acc(self.repo_dir, wt_path, "subagent-x", acc)
        self.assertEqual((wt, branch), (None, None))
        self.assertIn("[Worktree Branch 'subagent-x']", acc[0])
        self.assertIn("Some diff", acc[0])
        mock_cleanup.assert_called_once_with(self.repo_dir, wt_path, "subagent-x", keep_branch=True)

    def test_append_worktree_diff_to_acc_followup_keeps_branch(self):
        from unittest.mock import patch

        wt_path = os.path.join(self.temp_dir.name, "wt-append-fu")
        os.makedirs(wt_path, exist_ok=True)
        acc = [""]
        with (
            patch.object(SubagentWorktreeManager, "get_worktree_diff_summary", return_value=("Fu diff", True)),
            patch.object(SubagentWorktreeManager, "cleanup_worktree") as mock_cleanup,
        ):
            wt, branch = SubagentWorktreeManager.append_worktree_diff_to_acc(
                self.repo_dir, wt_path, "subagent-x", acc, is_followup=True
            )
        self.assertEqual((wt, branch), (None, None))
        self.assertIn("Changes updated on branch 'subagent-x'", acc[0])
        mock_cleanup.assert_called_once_with(self.repo_dir, wt_path, "subagent-x", keep_branch=True)

    def test_append_worktree_diff_to_acc_no_changes_returns_paths(self):
        from unittest.mock import patch

        wt_path = os.path.join(self.temp_dir.name, "wt-append-nc")
        os.makedirs(wt_path, exist_ok=True)
        acc = [""]
        with patch.object(SubagentWorktreeManager, "get_worktree_diff_summary", return_value=("", False)):
            wt, branch = SubagentWorktreeManager.append_worktree_diff_to_acc(self.repo_dir, wt_path, "subagent-x", acc)
        self.assertEqual((wt, branch), (None, None))
        self.assertEqual(acc[0], "")


if __name__ == "__main__":
    unittest.main()
