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
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_dir, capture_output=True, text=True)

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
        task_id = "test-wt-12345"
        wt_path, branch_name = SubagentWorktreeManager.create_worktree(self.repo_dir, task_id)

        self.assertIsNotNone(wt_path)
        self.assertIsNotNone(branch_name)
        self.assertTrue(os.path.exists(wt_path))
        self.assertEqual(branch_name, f"subagent-{task_id}")

        # Modify file inside worktree
        wt_file = os.path.join(wt_path, "README.md")
        with open(wt_file, "a", encoding="utf-8") as f:
            f.write("Worktree edit\n")

        diff_summary, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(self.repo_dir, wt_path, branch_name)
        self.assertTrue(has_changes)
        self.assertIn("Worktree edit", diff_summary)

        # Cleanup keeping branch
        SubagentWorktreeManager.cleanup_worktree(self.repo_dir, wt_path, branch_name, keep_branch=True)
        self.assertFalse(os.path.exists(wt_path))

        # Check branch exists in repo
        res = subprocess.run(["git", "branch", "--list", branch_name], cwd=self.repo_dir, capture_output=True, text=True)
        self.assertIn(branch_name, res.stdout)

        # Clean up branch manually for test
        subprocess.run(["git", "branch", "-D", branch_name], cwd=self.repo_dir, capture_output=True, text=True)

    def test_cleanup_worktree_no_changes_deletes_branch(self):
        task_id = "test-wt-no-changes"
        wt_path, branch_name = SubagentWorktreeManager.create_worktree(self.repo_dir, task_id)

        diff_summary, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(self.repo_dir, wt_path, branch_name)
        self.assertFalse(has_changes)
        self.assertEqual(diff_summary, "")

        # Cleanup without keeping branch
        SubagentWorktreeManager.cleanup_worktree(self.repo_dir, wt_path, branch_name, keep_branch=False)
        self.assertFalse(os.path.exists(wt_path))

        res = subprocess.run(["git", "branch", "--list", branch_name], cwd=self.repo_dir, capture_output=True, text=True)
        self.assertNotIn(branch_name, res.stdout)


if __name__ == "__main__":
    unittest.main()
