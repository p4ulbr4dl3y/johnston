"""Coverage-focused tests for GitCheckpointManager error/edge paths."""

import os
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from core.infrastructure.storage.git_checkpoint import GitCheckpointManager


def _cp(rc, out="", err=""):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr=err)


class TestCoverShadowExclude:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ensure_shadow_exclude_writes_leading_newline_when_no_trailing(self):
        info_dir = os.path.join(self.tmp, "info")
        os.makedirs(info_dir, exist_ok=True)
        exclude = os.path.join(info_dir, "exclude")
        with open(exclude, "w", encoding="utf-8") as f:
            f.write("existingpattern")
        GitCheckpointManager._ensure_shadow_exclude(self.tmp)
        with open(exclude, "r", encoding="utf-8") as f:
            content = f.read()
        assert content.index("\n") == len("existingpattern")

    def test_ensure_shadow_exclude_swallows_error(self):
        with patch("core.infrastructure.storage.git_checkpoint.os.makedirs", side_effect=OSError("boom")):
            GitCheckpointManager._ensure_shadow_exclude(self.tmp)  # must not raise


class TestCoverShadowIndexEnv:
    def test_shadow_index_env_remove_error_swallowed(self):
        tmp = tempfile.mkdtemp()
        try:
            with patch("core.infrastructure.storage.git_checkpoint.os.remove", side_effect=OSError("boom")):
                with GitCheckpointManager._shadow_index_env(tmp, tmp) as env:
                    with open(env["GIT_INDEX_FILE"], "w", encoding="utf-8") as f:
                        f.write("x")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_shadow_index_env_removes_temp_index(self):
        tmp = tempfile.mkdtemp()
        try:
            with GitCheckpointManager._shadow_index_env(tmp, tmp) as env:
                with open(env["GIT_INDEX_FILE"], "w", encoding="utf-8") as f:
                    f.write("x")
                idx = env["GIT_INDEX_FILE"]
            assert not os.path.exists(idx)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCoverEnsureGitRepo:
    def test_ensure_git_repo_init_fails(self):
        tmp = tempfile.mkdtemp()
        try:
            def fake(args, **kw):
                if args[0] in ("rev-parse", "init"):
                    return _cp(1)
                return _cp(0, "x")

            with patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=(tmp, tmp)):
                with patch("core.infrastructure.storage.git_checkpoint.run_git", side_effect=fake):
                    assert GitCheckpointManager.ensure_git_repo(tmp) is False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ensure_git_repo_commit_tree_fails(self):
        tmp = tempfile.mkdtemp()
        try:
            def fake(args, **kw):
                cmd = args[0]
                if cmd == "rev-parse":
                    return _cp(1)
                if cmd == "mktree":
                    return _cp(0, "tree123")
                if cmd == "commit-tree":
                    return _cp(1)
                return _cp(0, "x")

            with patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=(tmp, tmp)):
                with patch.object(GitCheckpointManager, "_ensure_shadow_exclude"):
                    with patch("core.infrastructure.storage.git_checkpoint.run_git", side_effect=fake):
                        assert GitCheckpointManager.ensure_git_repo(tmp) is False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCoverCreateCheckpoint:
    def test_create_checkpoint_auto_init_chained_fail(self):
        with (
            patch.object(GitCheckpointManager, "is_valid_checkpoint_target", return_value=True),
            patch.object(GitCheckpointManager, "ensure_git_repo", return_value=False),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
        ):
            assert GitCheckpointManager.create_checkpoint("s", 0, project_path="/w") is None

    def test_create_checkpoint_auto_init_false_not_git(self):
        with (
            patch.object(GitCheckpointManager, "is_valid_checkpoint_target", return_value=True),
            patch.object(GitCheckpointManager, "is_git_repo", return_value=False),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
        ):
            assert GitCheckpointManager.create_checkpoint("s", 0, project_path="/w", auto_init=False) is None

    def test_create_checkpoint_head_fails(self):
        with (
            patch.object(GitCheckpointManager, "is_valid_checkpoint_target", return_value=True),
            patch.object(GitCheckpointManager, "ensure_git_repo", return_value=True),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
            patch("core.infrastructure.storage.git_checkpoint.run_git", return_value=_cp(1)),
        ):
            assert GitCheckpointManager.create_checkpoint("s", 0, project_path="/w") is None

    def _run_create(self, write_res=_cp(0, "TREE"), commit_res=_cp(0, "COMMIT"), ref_res=_cp(0)):
        def fake(args, **kw):
            cmd = args[0]
            if cmd == "rev-parse":
                return _cp(0, "HEADHASH")
            if cmd == "add":
                return _cp(0)
            if cmd == "write-tree":
                return write_res
            if cmd == "commit-tree":
                return commit_res
            if cmd == "update-ref":
                return ref_res
            return _cp(0, "")

        with (
            patch.object(GitCheckpointManager, "is_valid_checkpoint_target", return_value=True),
            patch.object(GitCheckpointManager, "ensure_git_repo", return_value=True),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
            patch("core.infrastructure.storage.git_checkpoint.run_git", side_effect=fake),
        ):
            return GitCheckpointManager.create_checkpoint("s", 0, project_path="/w")

    def test_create_checkpoint_write_tree_fails(self):
        assert self._run_create(write_res=_cp(1)) is None

    def test_create_checkpoint_commit_tree_fails(self):
        assert self._run_create(commit_res=_cp(1)) is None

    def test_create_checkpoint_update_ref_fails(self):
        assert self._run_create(ref_res=_cp(1)) is None

    def test_create_checkpoint_success(self):
        assert self._run_create() == "COMMIT"


class TestCoverRestoreCheckpoint:
    def test_restore_not_git_repo_returns_false(self):
        with (
            patch.object(GitCheckpointManager, "is_git_repo", return_value=False),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
        ):
            assert GitCheckpointManager.restore_checkpoint("s", 0, project_path="/w") is False

    def _run_restore(self, cat_res=_cp(0, "tree T\nparent P\n"), read_res=_cp(0), raise_read=False):
        def fake(args, **kw):
            cmd = args[0]
            if cmd == "rev-parse":
                return _cp(0, "SHA")
            if cmd == "cat-file":
                return cat_res
            if cmd == "read-tree":
                if raise_read:
                    raise RuntimeError("boom")
                return read_res
            return _cp(0, "")

        with (
            patch.object(GitCheckpointManager, "is_git_repo", return_value=True),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
            patch("core.infrastructure.storage.git_checkpoint.run_git", side_effect=fake),
        ):
            return GitCheckpointManager.restore_checkpoint("s", 0, project_path="/w")

    def test_restore_cat_file_fails(self):
        assert self._run_restore(cat_res=_cp(1)) is False

    def test_restore_read_tree_fails(self):
        assert self._run_restore(read_res=_cp(1)) is False

    def test_restore_exception(self):
        assert self._run_restore(raise_read=True) is False

    def test_restore_success(self):
        assert self._run_restore() is True


class TestCoverPurge:
    def test_purge_not_git_repo(self):
        with (
            patch.object(GitCheckpointManager, "is_git_repo", return_value=False),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
        ):
            GitCheckpointManager.purge_checkpoints_after("s", 0, project_path="/w")  # must not raise

    def test_purge_refs_command_fails(self):
        with (
            patch.object(GitCheckpointManager, "is_git_repo", return_value=True),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
            patch("core.infrastructure.storage.git_checkpoint.run_git", return_value=_cp(1)),
        ):
            GitCheckpointManager.purge_checkpoints_after("s", 0, project_path="/w")

    def test_purge_skips_invalid_index(self):
        with (
            patch.object(GitCheckpointManager, "is_git_repo", return_value=True),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
            patch(
                "core.infrastructure.storage.git_checkpoint.run_git",
                return_value=_cp(0, "refs/johnston/checkpoints/s/notanumber\n"),
            ),
        ):
            GitCheckpointManager.purge_checkpoints_after("s", 0, project_path="/w")

    def test_purge_skips_blank_ref_line(self):
        with (
            patch.object(GitCheckpointManager, "is_git_repo", return_value=True),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
            patch(
                "core.infrastructure.storage.git_checkpoint.run_git",
                return_value=_cp(0, "refs/johnston/checkpoints/s/1\n\n"),
            ),
        ):
            GitCheckpointManager.purge_checkpoints_after("s", 0, project_path="/w")  # must not raise


class TestCoverGetDiffStats:
    def test_get_diff_stats_batch_empty_indices(self):
        with patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")):
            out = GitCheckpointManager.get_diff_stats_batch("s", [])
        assert out == {}

    def test_get_diff_stats_batch_not_git_repo(self):
        with (
            patch.object(GitCheckpointManager, "is_git_repo", return_value=False),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
        ):
            out = GitCheckpointManager.get_diff_stats_batch("s", [0], project_path="/w")
        assert out == {0: None}

    def _run_batch(self, add_res=_cp(0), diff_res=_cp(0, "")):
        def fake(args, **kw):
            cmd = args[0]
            if cmd == "add":
                return add_res
            if cmd == "rev-parse":
                return _cp(0, "SHA")
            if cmd == "diff":
                return diff_res
            return _cp(0, "")

        with (
            patch.object(GitCheckpointManager, "is_git_repo", return_value=True),
            patch.object(GitCheckpointManager, "_ensure_shadow_exclude"),
            patch.object(GitCheckpointManager, "_get_shadow_dir", return_value=("/s", "/w")),
            patch("core.infrastructure.storage.git_checkpoint.run_git", side_effect=fake),
        ):
            return GitCheckpointManager.get_diff_stats_batch("s", [0], project_path="/w")

    def test_add_fails(self):
        assert self._run_batch(add_res=_cp(1)) == {0: None}

    def test_diff_fails(self):
        assert self._run_batch(diff_res=_cp(1)) == {0: None}

    def test_no_changes(self):
        assert self._run_batch() == {0: "no changes"}
