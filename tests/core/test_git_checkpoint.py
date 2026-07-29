import os
import shutil
import subprocess
import tempfile
import unittest

from core.git_checkpoint import GitCheckpointManager


class TestGitCheckpointManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _init_git_repo(self) -> str:
        subprocess.run(["git", "init"], cwd=self.tmp_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=self.tmp_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.tmp_dir, capture_output=True, check=True)

        initial_file = os.path.join(self.tmp_dir, "initial.txt")
        with open(initial_file, "w") as f:
            f.write("initial content\n")

        subprocess.run(["git", "add", "initial.txt"], cwd=self.tmp_dir, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=self.tmp_dir, capture_output=True, check=True)
        return self.tmp_dir

    def test_non_git_repo(self):
        self.assertFalse(GitCheckpointManager.is_git_repo(self.tmp_dir))
        sha_no_init = GitCheckpointManager.create_checkpoint("s1", 0, project_path=self.tmp_dir, auto_init=False)
        self.assertIsNone(sha_no_init)
        # Non-git repo must return None even with auto_init=True
        sha_auto = GitCheckpointManager.create_checkpoint("s1", 0, project_path=self.tmp_dir, auto_init=True)
        self.assertIsNone(sha_auto)

    def test_home_and_root_dirs(self):
        home_dir = os.path.expanduser("~")
        self.assertFalse(GitCheckpointManager.is_valid_checkpoint_target(home_dir))
        self.assertFalse(GitCheckpointManager.is_valid_checkpoint_target("/"))

    def test_create_and_restore_checkpoint(self):
        repo_path = self._init_git_repo()

        # Create modifications
        mod_file = os.path.join(repo_path, "initial.txt")
        with open(mod_file, "w") as f:
            f.write("modified before checkpoint")

        untracked_file = os.path.join(repo_path, "untracked.txt")
        with open(untracked_file, "w") as f:
            f.write("untracked before checkpoint")

        sha = GitCheckpointManager.create_checkpoint("session_123", 0, project_path=repo_path)
        self.assertIsNotNone(sha)

        # Make further modifications / create new files after checkpoint
        with open(mod_file, "w") as f:
            f.write("modified AFTER checkpoint")

        new_file = os.path.join(repo_path, "new_after_checkpoint.txt")
        with open(new_file, "w") as f:
            f.write("created after checkpoint")

        # Verify state before restore
        self.assertTrue(os.path.exists(new_file))

        # Restore checkpoint 0
        restored = GitCheckpointManager.restore_checkpoint("session_123", 0, project_path=repo_path)
        self.assertTrue(restored)

        # Verify state after restore
        with open(mod_file, "r") as f:
            self.assertEqual(f.read(), "modified before checkpoint")
        with open(untracked_file, "r") as f:
            self.assertEqual(f.read(), "untracked before checkpoint")

        self.assertFalse(os.path.exists(new_file))

    def test_purge_checkpoints(self):
        repo_path = self._init_git_repo()

        sha0 = GitCheckpointManager.create_checkpoint("session_456", 0, project_path=repo_path)
        sha1 = GitCheckpointManager.create_checkpoint("session_456", 1, project_path=repo_path)
        sha2 = GitCheckpointManager.create_checkpoint("session_456", 2, project_path=repo_path)

        self.assertIsNotNone(sha0)
        self.assertIsNotNone(sha1)
        self.assertIsNotNone(sha2)

        # Purge after index 0
        GitCheckpointManager.purge_checkpoints_after("session_456", 0, project_path=repo_path)

        # Checkpoint 0 should be restorable, 1 and 2 should fail
        self.assertTrue(GitCheckpointManager.restore_checkpoint("session_456", 0, project_path=repo_path))
        self.assertFalse(GitCheckpointManager.restore_checkpoint("session_456", 1, project_path=repo_path))
        self.assertFalse(GitCheckpointManager.restore_checkpoint("session_456", 2, project_path=repo_path))

    def test_delete_session_checkpoints(self):
        repo_path = self._init_git_repo()
        GitCheckpointManager.create_checkpoint("session_789", 0, project_path=repo_path)
        GitCheckpointManager.delete_session_checkpoints("session_789", project_path=repo_path)
        self.assertFalse(GitCheckpointManager.restore_checkpoint("session_789", 0, project_path=repo_path))

    def test_get_diff_stats(self):
        repo_path = self._init_git_repo()
        GitCheckpointManager.create_checkpoint("session_stat", 0, project_path=repo_path)

        # No changes initially
        stat_same = GitCheckpointManager.get_diff_stats("session_stat", 0, project_path=repo_path)
        self.assertEqual(stat_same, "no changes")

        # Make modifications
        mod_file = os.path.join(repo_path, "initial.txt")
        with open(mod_file, "a") as f:
            f.write("added line 1\nadded line 2")

        stat_diff = GitCheckpointManager.get_diff_stats("session_stat", 0, project_path=repo_path)
        self.assertEqual(stat_diff, "+2 / -0")

    def test_default_excludes_without_gitignore(self):
        repo_path = self._init_git_repo()
        # Create a venv directory and node_modules directory without a .gitignore file
        venv_dir = os.path.join(repo_path, "venv")
        os.makedirs(venv_dir, exist_ok=True)
        with open(os.path.join(venv_dir, "lib.py"), "w") as f:
            f.write("print('ignored')\n")

        node_dir = os.path.join(repo_path, "node_modules")
        os.makedirs(node_dir, exist_ok=True)
        with open(os.path.join(node_dir, "pkg.json"), "w") as f:
            f.write("{}\n")

        sha = GitCheckpointManager.create_checkpoint("session_excl", 0, project_path=repo_path)
        self.assertIsNotNone(sha)

        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)
        ls_res = GitCheckpointManager._run_git(["ls-tree", "-r", "--name-only", sha], cwd=shadow_dir)
        tracked_files = ls_res.stdout.splitlines()

        self.assertNotIn("venv/lib.py", tracked_files)
        self.assertNotIn("node_modules/pkg.json", tracked_files)


if __name__ == "__main__":
    unittest.main()
