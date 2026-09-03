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

    def test_finalize_turn_detects_changes(self):
        repo_path = self._init_git_repo()
        sid = "session_turn_finalize"

        sha0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(sha0)

        # No changes initially
        no_changes = GitCheckpointManager.finalize_turn(sid, 0, project_path=repo_path)
        self.assertEqual(no_changes, [])

        # Modify a file and create a new file
        with open(os.path.join(repo_path, "initial.txt"), "w") as f:
            f.write("turn modified content\n")
        with open(os.path.join(repo_path, "turn_new.txt"), "w") as f:
            f.write("new file in turn\n")

        touched = GitCheckpointManager.finalize_turn(sid, 0, project_path=repo_path)
        self.assertIn("initial.txt", touched)
        self.assertIn("turn_new.txt", touched)

    def test_get_diff_details_batch_with_scoped_files(self):
        repo_path = self._init_git_repo()
        sid = "session_scoped_batch"

        sha0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(sha0)

        # Modify initial.txt and external.txt
        with open(os.path.join(repo_path, "initial.txt"), "w") as f:
            f.write("agent modified\n")
        with open(os.path.join(repo_path, "external.txt"), "w") as f:
            f.write("user modified\n")

        # When scoped_files has empty list for index 0 -> reports 'no changes'
        res_empty = GitCheckpointManager.get_diff_details_batch(
            sid, [0], project_path=repo_path, scoped_files={0: []}
        )
        self.assertEqual(res_empty[0], ("no changes", []))

        # When scoped_files specifies only initial.txt -> only initial.txt is reported
        res_scoped = GitCheckpointManager.get_diff_details_batch(
            sid, [0], project_path=repo_path, scoped_files={0: ["initial.txt"]}
        )
        self.assertIn("1 file", res_scoped[0][0])
        self.assertEqual(res_scoped[0][1], ["initial.txt"])

    def test_restore_checkpoint_selective_preserves_external_files(self):
        repo_path = self._init_git_repo()
        sid = "session_selective_restore"

        sha0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(sha0)

        # Agent edits code_file.txt and creates agent_new.txt
        code_file = os.path.join(repo_path, "initial.txt")
        with open(code_file, "w") as f:
            f.write("agent edits\n")
        agent_new = os.path.join(repo_path, "agent_new.txt")
        with open(agent_new, "w") as f:
            f.write("created by agent\n")

        # User edits external_file.txt
        ext_file = os.path.join(repo_path, "user_external.txt")
        with open(ext_file, "w") as f:
            f.write("user manual work\n")

        # Selective restore targeting only agent files
        restored = GitCheckpointManager.restore_checkpoint(
            sid, 0, project_path=repo_path, files_to_restore=["initial.txt", "agent_new.txt"]
        )
        self.assertTrue(restored)

        # initial.txt is reverted to checkpoint 0
        with open(code_file, "r") as f:
            self.assertEqual(f.read(), "initial content\n")

        # agent_new.txt is deleted
        self.assertFalse(os.path.exists(agent_new))

        # user_external.txt is PRESERVED!
        self.assertTrue(os.path.exists(ext_file))
        with open(ext_file, "r") as f:
            self.assertEqual(f.read(), "user manual work\n")

    def test_get_checkpoint_diff_with_scoped_files(self):
        repo_path = self._init_git_repo()
        sid = "session_scoped_diff"

        GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        with open(os.path.join(repo_path, "initial.txt"), "w") as f:
            f.write("new content\n")
        with open(os.path.join(repo_path, "other.txt"), "w") as f:
            f.write("other content\n")

        # Scoped to only initial.txt
        diff_items = GitCheckpointManager.get_checkpoint_diff(
            sid, 0, project_path=repo_path, scoped_files=["initial.txt"]
        )
        self.assertEqual(len(diff_items), 1)
        self.assertEqual(diff_items[0][0], "initial.txt")

        # Scoped to empty list
        diff_empty = GitCheckpointManager.get_checkpoint_diff(
            sid, 0, project_path=repo_path, scoped_files=[]
        )
        self.assertEqual(diff_empty, [])

    def _shadow_tree(self, shadow_dir, commit_sha):
        res = gcp.run_git(["rev-parse", f"{commit_sha}^{{tree}}"], cwd=shadow_dir)
        self.assertEqual(res.returncode, 0)
        return res.stdout.strip()

    def _full_workspace_tree(self, repo_path, shadow_dir):
        """Reference oracle: tree a full `add -A` snapshot would produce."""
        with GitCheckpointManager._shadow_index_env(shadow_dir, repo_path) as env:
            add_res = gcp.run_git(["add", "-A"], cwd=repo_path, env=env)
            self.assertEqual(add_res.returncode, 0)
            tree_res = gcp.run_git(["write-tree"], cwd=repo_path, env=env)
            self.assertEqual(tree_res.returncode, 0)
            return tree_res.stdout.strip()

    def _write(self, repo_path, name, content):
        with open(os.path.join(repo_path, name), "w") as f:
            f.write(content)

    def test_delta_checkpoint_tree_matches_full_workspace(self):
        """Delta-built checkpoint 2 must produce EXACTLY the full workspace tree.

        Covers edit, new-file, delete-file deltas, restore-from-delta commit,
        and diff correctness (checkpoint 1 -> 2 and 2 -> workspace).
        """
        repo_path = self._init_git_repo()
        sid = "session_delta"

        for name, content in (("a.txt", "a0\n"), ("b.txt", "b0\n"), ("d.txt", "d0\n")):
            self._write(repo_path, name, content)

        cp0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(cp0)
        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)

        # Turn 1 delta: edit a, edit b, create c, delete d.
        self._write(repo_path, "a.txt", "a1\n")
        self._write(repo_path, "b.txt", "b1\n")
        self._write(repo_path, "c.txt", "c1\n")
        os.remove(os.path.join(repo_path, "d.txt"))

        cp1 = GitCheckpointManager.create_checkpoint(sid, 1, project_path=repo_path)
        self.assertIsNotNone(cp1)
        self.assertNotEqual(cp0, cp1)

        # (a) delta tree == full-snapshot tree.
        tree1 = self._shadow_tree(shadow_dir, cp1)
        self.assertEqual(tree1, self._full_workspace_tree(repo_path, shadow_dir))

        # Parent of the delta commit is the previous checkpoint.
        cat_res = gcp.run_git(["cat-file", "-p", cp1], cwd=shadow_dir)
        self.assertEqual(cat_res.returncode, 0)
        parents = [line.split()[1] for line in cat_res.stdout.splitlines() if line.startswith("parent ")]
        self.assertEqual(parents, [cp0])

        # (g) diff between checkpoint trees shows exactly the delta paths.
        diff_res = gcp.run_git(["diff", "--name-only", f"{cp0}^{{tree}}", f"{cp1}^{{tree}}"], cwd=shadow_dir)
        self.assertEqual(diff_res.returncode, 0)
        self.assertEqual(sorted(diff_res.stdout.splitlines()), ["a.txt", "b.txt", "c.txt", "d.txt"])

        # (g) workspace (== checkpoint 2 state) diffs against checkpoint 2 = none,
        # against checkpoint 1 = the four delta paths.
        self.assertEqual(GitCheckpointManager.get_checkpoint_diff(sid, 1, project_path=repo_path), [])
        cp_diff = GitCheckpointManager.get_checkpoint_diff(sid, 0, project_path=repo_path)
        self.assertEqual(sorted(d[0] for d in cp_diff), ["a.txt", "b.txt", "c.txt", "d.txt"])

        # (c) restore from the delta-built checkpoint 2 -> workspace == cp1 state.
        self._write(repo_path, "a.txt", "a2\n")
        os.remove(os.path.join(repo_path, "c.txt"))
        self.assertTrue(GitCheckpointManager.restore_checkpoint(sid, 1, project_path=repo_path))
        with open(os.path.join(repo_path, "a.txt")) as f:
            self.assertEqual(f.read(), "a1\n")
        with open(os.path.join(repo_path, "b.txt")) as f:
            self.assertEqual(f.read(), "b1\n")
        with open(os.path.join(repo_path, "c.txt")) as f:
            self.assertEqual(f.read(), "c1\n")
        self.assertFalse(os.path.exists(os.path.join(repo_path, "d.txt")))

    def test_delta_checkpoint_stages_only_changed_paths(self):
        """The delta snapshot must stage exactly [A, B, C, D] and nothing else."""
        repo_path = self._init_git_repo()
        sid = "session_delta_staged"

        for name, content in (("a.txt", "a0\n"), ("b.txt", "b0\n"), ("d.txt", "d0\n")):
            self._write(repo_path, name, content)
        cp0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(cp0)

        self._write(repo_path, "a.txt", "a1\n")
        self._write(repo_path, "b.txt", "b1\n")
        self._write(repo_path, "c.txt", "c1\n")
        os.remove(os.path.join(repo_path, "d.txt"))

        captured = {}
        original = gcp.run_git

        def spy(args, **kw):
            if "--pathspec-file-nul" in args:
                captured["input"] = kw.get("input", "")
                captured["args"] = list(args)
            return original(args, **kw)

        with mock.patch.object(gcp, "run_git", side_effect=spy):
            cp1 = GitCheckpointManager.create_checkpoint(sid, 1, project_path=repo_path)
        self.assertIsNotNone(cp1)
        self.assertIn("--literal-pathspecs", captured["args"])
        self.assertEqual(set(captured["input"].split("\0")), {"a.txt", "b.txt", "c.txt", "d.txt"})

    def test_delta_checkpoint_first_checkpoint_uses_full_add(self):
        """No prior ref -> full `add -A` fallback (legacy path)."""
        repo_path = self._init_git_repo()
        sid = "session_delta_first"

        self._write(repo_path, "a.txt", "a0\n")

        full_add_calls = []
        original = gcp.run_git

        def spy(args, **kw):
            if args == ["add", "-A"]:
                full_add_calls.append(args)
            return original(args, **kw)

        with mock.patch.object(gcp, "run_git", side_effect=spy):
            cp0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(cp0)
        self.assertEqual(len(full_add_calls), 1)

    def test_delta_checkpoint_no_changes_reuses_tree(self):
        """Unchanged workspace -> new commit reuses the previous tree (no index rebuild)."""
        repo_path = self._init_git_repo()
        sid = "session_delta_noop"

        cp0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(cp0)
        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)

        index_ops = []
        original = gcp.run_git

        def spy(args, **kw):
            if args[0] in ("read-tree", "write-tree") or "--pathspec-file-nul" in args:
                index_ops.append(args[0])
            return original(args, **kw)

        with mock.patch.object(gcp, "run_git", side_effect=spy):
            cp1 = GitCheckpointManager.create_checkpoint(sid, 1, project_path=repo_path)
        self.assertIsNotNone(cp1)
        self.assertNotEqual(cp0, cp1)
        # read-tree seeds the index for change detection, but the no-op delta
        # must skip the targeted add and the tree rebuild entirely.
        self.assertEqual(index_ops, ["read-tree"])
        self.assertEqual(self._shadow_tree(shadow_dir, cp1), self._shadow_tree(shadow_dir, cp0))
        self.assertEqual(self._shadow_tree(shadow_dir, cp1), self._full_workspace_tree(repo_path, shadow_dir))

        # Restoring the no-op checkpoint keeps the workspace unchanged.
        self.assertTrue(GitCheckpointManager.restore_checkpoint(sid, 1, project_path=repo_path))
        with open(os.path.join(repo_path, "initial.txt")) as f:
            self.assertEqual(f.read(), "initial content\n")

    def test_delta_checkpoint_untracked_only_changes(self):
        """Delta whose only changes are new untracked files."""
        repo_path = self._init_git_repo()
        sid = "session_delta_untracked"

        cp0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(cp0)
        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)

        self._write(repo_path, "u1.txt", "u1\n")
        self._write(repo_path, "u2.txt", "u2\n")

        cp1 = GitCheckpointManager.create_checkpoint(sid, 1, project_path=repo_path)
        self.assertIsNotNone(cp1)
        self.assertEqual(self._shadow_tree(shadow_dir, cp1), self._full_workspace_tree(repo_path, shadow_dir))

        # Restore brings both new files back.
        os.remove(os.path.join(repo_path, "u1.txt"))
        os.remove(os.path.join(repo_path, "u2.txt"))
        self.assertTrue(GitCheckpointManager.restore_checkpoint(sid, 1, project_path=repo_path))
        for name in ("u1.txt", "u2.txt"):
            self.assertTrue(os.path.exists(os.path.join(repo_path, name)))

    def test_delta_checkpoint_falls_back_to_full_add_when_detection_fails(self):
        """Delta detection failure must fall back to a full `add -A` snapshot."""
        repo_path = self._init_git_repo()
        sid = "session_delta_fallback"

        cp0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(cp0)
        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)

        self._write(repo_path, "initial.txt", "modified later\n")
        self._write(repo_path, "newfile.txt", "new\n")

        original = gcp.run_git

        def spy(args, **kw):
            if args and args[0] == "ls-files":
                return subprocess.CompletedProcess(["git"] + args, 1, "", "mock detection failure")
            return original(args, **kw)

        with mock.patch.object(gcp, "run_git", side_effect=spy):
            cp1 = GitCheckpointManager.create_checkpoint(sid, 1, project_path=repo_path)
        self.assertIsNotNone(cp1)
        # Fallback snapshot must still capture the exact workspace state.
        self.assertEqual(self._shadow_tree(shadow_dir, cp1), self._full_workspace_tree(repo_path, shadow_dir))
        self.assertTrue(GitCheckpointManager.restore_checkpoint(sid, 1, project_path=repo_path))

    def test_delta_checkpoint_after_rewind_continue(self):
        """Checkpointing after a rewind restore must stay correct (chain + tree)."""
        repo_path = self._init_git_repo()
        sid = "session_delta_rewind"

        self._write(repo_path, "a.txt", "a0\n")
        cp0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(cp0)
        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)

        self._write(repo_path, "a.txt", "a1\n")
        cp1 = GitCheckpointManager.create_checkpoint(sid, 1, project_path=repo_path)
        self.assertIsNotNone(cp1)

        # Rewind to checkpoint 0, then continue the session with a new turn.
        self.assertTrue(GitCheckpointManager.restore_checkpoint(sid, 0, project_path=repo_path))
        self._write(repo_path, "b.txt", "b-after-rewind\n")
        cp2 = GitCheckpointManager.create_checkpoint(sid, 2, project_path=repo_path)
        self.assertIsNotNone(cp2)

        # Delta-built tree still equals the workspace state.
        self.assertEqual(self._shadow_tree(shadow_dir, cp2), self._full_workspace_tree(repo_path, shadow_dir))
        # Parent chain: cp2 -> cp1 (nearest prior ref), even across the rewind.
        cat_res = gcp.run_git(["cat-file", "-p", cp2], cwd=shadow_dir)
        parents = [line.split()[1] for line in cat_res.stdout.splitlines() if line.startswith("parent ")]
        self.assertEqual(parents, [cp1])
        # Restore of the post-rewind checkpoint is exact.
        self._write(repo_path, "b.txt", "b-mutated\n")
        self.assertTrue(GitCheckpointManager.restore_checkpoint(sid, 2, project_path=repo_path))
        with open(os.path.join(repo_path, "b.txt")) as f:
            self.assertEqual(f.read(), "b-after-rewind\n")

    def test_delta_checkpoint_special_char_filenames(self):
        """Glob metacharacters in filenames must not expand during delta staging."""
        repo_path = self._init_git_repo()
        sid = "session_delta_glob"

        self._write(repo_path, "f[1].txt", "one\n")
        self._write(repo_path, "with space.txt", "space\n")
        cp0 = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo_path)
        self.assertIsNotNone(cp0)
        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo_path)

        self._write(repo_path, "f[1].txt", "one v2\n")
        self._write(repo_path, "new [x].txt", "new\n")

        captured = {}
        original = gcp.run_git

        def spy(args, **kw):
            if "--pathspec-file-nul" in args:
                captured["input"] = kw.get("input", "")
            return original(args, **kw)

        with mock.patch.object(gcp, "run_git", side_effect=spy):
            cp1 = GitCheckpointManager.create_checkpoint(sid, 1, project_path=repo_path)
        self.assertIsNotNone(cp1)
        self.assertEqual(set(captured["input"].split("\0")), {"f[1].txt", "new [x].txt"})
        self.assertEqual(self._shadow_tree(shadow_dir, cp1), self._full_workspace_tree(repo_path, shadow_dir))


if __name__ == "__main__":
    unittest.main()


