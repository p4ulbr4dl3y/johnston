import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from core.infrastructure.storage import git_checkpoint as gcp
from core.infrastructure.storage.git_checkpoint import GitCheckpointManager


class TestGitCheckpointManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _init_git_repo(self) -> str:
        subprocess.run(["git", "init"], cwd=self.tmp_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=self.tmp_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=self.tmp_dir, capture_output=True, check=True
        )

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

    def test_get_diff_details_batch(self):
        repo_path = self._init_git_repo()
        GitCheckpointManager.create_checkpoint("session_batch", 0, project_path=repo_path)

        mod_file = os.path.join(repo_path, "initial.txt")
        with open(mod_file, "a") as f:
            f.write("added line 1\n")
        GitCheckpointManager.create_checkpoint("session_batch", 1, project_path=repo_path)

        with open(mod_file, "a") as f:
            f.write("added line 2\n")

        batch_details = GitCheckpointManager.get_diff_details_batch("session_batch", [0, 1, 2], project_path=repo_path)
        self.assertEqual(batch_details[0], ("1 file, +2 / -0", ["initial.txt"]))
        self.assertEqual(batch_details[1], ("1 file, +1 / -0", ["initial.txt"]))
        self.assertIsNone(batch_details[2])

    def test_get_checkpoint_diff_and_split(self):
        repo_path = self._init_git_repo()
        GitCheckpointManager.create_checkpoint("session_diff", 0, project_path=repo_path)

        mod_file = os.path.join(repo_path, "initial.txt")
        with open(mod_file, "a") as f:
            f.write("second line\n")

        new_file = os.path.join(repo_path, "added.txt")
        with open(new_file, "w") as f:
            f.write("new content\n")

        # Test diff with specific message index
        diffs = GitCheckpointManager.get_checkpoint_diff("session_diff", 0, project_path=repo_path)
        self.assertEqual(len(diffs), 2)
        paths = [d[0] for d in diffs]
        self.assertIn("initial.txt", paths)
        self.assertIn("added.txt", paths)

        # Test diff with message_index=None (finds earliest checkpoint 0)
        diffs_auto = GitCheckpointManager.get_checkpoint_diff("session_diff", None, project_path=repo_path)
        self.assertEqual(len(diffs_auto), 2)

        # Test empty diff on unmodified repo
        GitCheckpointManager.create_checkpoint("session_clean", 0, project_path=repo_path)
        clean_diffs = GitCheckpointManager.get_checkpoint_diff("session_clean", 0, project_path=repo_path)
        self.assertEqual(clean_diffs, [])

        # Test _split_git_diff with empty string
        self.assertEqual(GitCheckpointManager._split_git_diff(""), [])

    def test_purge_archives_and_recovery(self):
        repo_path = self._init_git_repo()
        sid = "session_archive"

        with open(os.path.join(repo_path, "f1.txt"), "w") as f:
            f.write("state 1\n")
        sha1 = GitCheckpointManager.create_checkpoint(sid, 1, project_path=repo_path)
        with open(os.path.join(repo_path, "f2.txt"), "w") as f:
            f.write("state 2\n")
        sha2 = GitCheckpointManager.create_checkpoint(sid, 2, project_path=repo_path)
        self.assertIsNotNone(sha1)
        self.assertIsNotNone(sha2)

        GitCheckpointManager.purge_checkpoints_after(sid, 0, project_path=repo_path)

        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)
        # Live refs are gone...
        self.assertFalse(GitCheckpointManager.restore_checkpoint(sid, 1, project_path=repo_path))
        self.assertFalse(GitCheckpointManager.restore_checkpoint(sid, 2, project_path=repo_path))
        # ...but the states survive in the archive namespace.
        arch_res = gcp.run_git(["rev-parse", "--verify", f"refs/johnston/archive/{sid}/1"], cwd=shadow_dir)
        self.assertEqual(arch_res.stdout.strip(), sha1)
        arch_res2 = gcp.run_git(["rev-parse", "--verify", f"refs/johnston/archive/{sid}/2"], cwd=shadow_dir)
        self.assertEqual(arch_res2.stdout.strip(), sha2)

        # Recovery: promoting an archived ref back makes the state restorable again.
        gcp.run_git(
            ["update-ref", GitCheckpointManager.get_ref_name(sid, 1), sha1],
            cwd=shadow_dir,
        )
        self.assertTrue(GitCheckpointManager.restore_checkpoint(sid, 1, project_path=repo_path))
        with open(os.path.join(repo_path, "f1.txt")) as f:
            self.assertEqual(f.read(), "state 1\n")

    def test_archive_refs_expire_after_ttl(self):
        repo_path = self._init_git_repo()
        sid = "session_expire"

        with open(os.path.join(repo_path, "f.txt"), "w") as f:
            f.write("data\n")
        self.assertIsNotNone(GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path))

        # target_message_index=-1 archives every checkpoint of the session.
        GitCheckpointManager.purge_checkpoints_after(sid, -1, project_path=repo_path)

        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)
        arch_ref = f"refs/johnston/archive/{sid}/0"
        self.assertEqual(gcp.run_git(["rev-parse", "--verify", arch_ref], cwd=shadow_dir).returncode, 0)

        # Jump past the TTL: the next purge pass must drop the expired archive ref.
        real_time = gcp.time.time
        with mock.patch.object(gcp.time, "time", return_value=real_time() + (GitCheckpointManager.ARCHIVE_TTL_DAYS + 1) * 86400):
            GitCheckpointManager.purge_checkpoints_after(sid, 10**9, project_path=repo_path)

        self.assertNotEqual(gcp.run_git(["rev-parse", "--verify", arch_ref], cwd=shadow_dir).returncode, 0)

    def test_create_checkpoint_fails_cleanly_when_add_fails(self):
        repo_path = self._init_git_repo()
        sid = "session_addfail"

        original_run_git = gcp.run_git

        def fake_run_git(args, **kwargs):
            if args and args[0] == "add":
                return subprocess.CompletedProcess(
                    args=["git"] + args, returncode=1, stdout="", stderr="mock staging failure"
                )
            return original_run_git(args, **kwargs)

        with mock.patch.object(gcp, "run_git", side_effect=fake_run_git):
            sha = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)

        # A failed/partial staging must never produce a checkpoint: restoring it
        # would delete the missing files from the workspace.
        self.assertIsNone(sha)
        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)
        ref_res = gcp.run_git(["rev-parse", "--verify", GitCheckpointManager.get_ref_name(sid, 0)], cwd=shadow_dir)
        self.assertNotEqual(ref_res.returncode, 0)

    def test_stale_index_lock_cleanup_respects_age(self):
        repo_path = self._init_git_repo()
        GitCheckpointManager.ensure_git_repo(repo_path)
        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)

        lock_file = os.path.join(shadow_dir, "index.lock")
        with open(lock_file, "w") as f:
            f.write("")

        # Fresh lock may belong to another running process — left alone.
        GitCheckpointManager._ensure_shadow_exclude(shadow_dir)
        self.assertTrue(os.path.exists(lock_file))

        # Old lock is stale (crashed process) — removed.
        old_ts = time.time() - (GitCheckpointManager.STALE_LOCK_SECONDS + 60)
        os.utime(lock_file, (old_ts, old_ts))
        GitCheckpointManager._ensure_shadow_exclude(shadow_dir)
        self.assertFalse(os.path.exists(lock_file))

    def test_secret_files_are_excluded_from_snapshots(self):
        repo_path = self._init_git_repo()
        sid = "session_secrets"

        for name in (".env", ".env.local", "server.pem", "id_rsa"):
            with open(os.path.join(repo_path, name), "w") as f:
                f.write("SECRET\n")

        sha = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(sha)

        diffs = GitCheckpointManager.get_checkpoint_diff(sid, 0, project_path=repo_path)
        paths = [d[0] for d in diffs]
        for name in (".env", ".env.local", "server.pem", "id_rsa"):
            self.assertNotIn(name, paths)

    def test_get_diff_details_batch_parallel(self):
        repo_path = self._init_git_repo()
        sid = "session_batch_diff"

        # Create multiple checkpoints across message indices
        indices = [0, 1, 2]
        for idx in indices:
            test_file = os.path.join(repo_path, f"file_{idx}.txt")
            with open(test_file, "w") as f:
                f.write(f"content {idx}\n")
            sha = GitCheckpointManager.create_checkpoint(sid, idx, project_path=repo_path)
            self.assertIsNotNone(sha)

        # Query batch diff details
        results = GitCheckpointManager.get_diff_details_batch(sid, indices, project_path=repo_path)
        self.assertIsInstance(results, dict)
        for idx in indices:
            self.assertIn(idx, results)
            summary_str, file_names = results[idx]
            self.assertIsInstance(summary_str, str)
            self.assertIsInstance(file_names, list)

        # Diff vs checkpoint 0 contains subsequent added files
        self.assertTrue(any("file_1.txt" in f for f in results[0][1]))
        self.assertTrue(any("file_2.txt" in f for f in results[0][1]))

    def test_checkpoint_port_resolution(self):
        from core.domain.ports.checkpoint import (
            CheckpointPort,
            get_checkpoint_manager,
            set_default_checkpoint_manager,
        )

        self.assertIsInstance(GitCheckpointManager, CheckpointPort)
        self.assertIs(get_checkpoint_manager(), GitCheckpointManager)

        # Custom manager injection
        mock_mgr = mock.MagicMock(spec=CheckpointPort)
        set_default_checkpoint_manager(mock_mgr)
        self.assertIs(get_checkpoint_manager(), mock_mgr)

        # Restore default
        set_default_checkpoint_manager(GitCheckpointManager)
        self.assertIs(get_checkpoint_manager(), GitCheckpointManager)


if __name__ == "__main__":
    unittest.main()


