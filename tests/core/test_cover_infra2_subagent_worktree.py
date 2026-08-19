"""Coverage-focused tests for SubagentWorktreeManager edge paths."""

import os
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from core.infrastructure.platform import paths
from core.infrastructure.runtime.subagent_worktree import SubagentWorktreeManager


def _cp(rc, out=""):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr="")


class TestCoverWorktree:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)
        wt = os.path.join(paths.WORKTREES_DIR, "cov-session")
        if os.path.isdir(wt):
            shutil.rmtree(wt, ignore_errors=True)

    def test_create_worktree_uses_existing_branch(self):
        wt_path = os.path.join(paths.WORKTREES_DIR, "cov-session")

        def fake(args, **kw):
            if len(args) >= 2 and args[0] == "worktree" and args[1] == "remove":
                return _cp(0)
            if len(args) >= 2 and args[0] == "worktree" and args[1] == "add":
                os.makedirs(wt_path, exist_ok=True)
                return _cp(0)
            return _cp(0, "ok")

        with (
            patch.object(SubagentWorktreeManager, "is_git_repo", return_value=True),
            patch("core.infrastructure.runtime.subagent_worktree.run_git", side_effect=fake),
        ):
            path, branch = SubagentWorktreeManager.create_worktree(self.tmp, "cov-session", "feature-x")
        assert path == wt_path
        assert branch == "feature-x"

    def test_attach_worktree_non_git(self):
        assert SubagentWorktreeManager.attach_worktree(self.tmp, "a", "b") is None

    def test_attach_worktree_success(self):
        wt_path = os.path.join(paths.WORKTREES_DIR, "cov-session")

        def fake(args, **kw):
            if args[0] == "worktree":
                os.makedirs(wt_path, exist_ok=True)
            return _cp(0)

        with (
            patch.object(SubagentWorktreeManager, "is_git_repo", return_value=True),
            patch("core.infrastructure.runtime.subagent_worktree.run_git", side_effect=fake),
        ):
            assert SubagentWorktreeManager.attach_worktree(self.tmp, "cov-session", "feature-x") == wt_path
        import shutil

        shutil.rmtree(wt_path, ignore_errors=True)


class TestCoverAsyncWrappers:
    async def test_create_worktree_async(self):
        with patch.object(SubagentWorktreeManager, "_create_worktree_impl", return_value=("/w", "b")):
            out = await SubagentWorktreeManager.create_worktree_async("/p", "s", "b")
        assert out == ("/w", "b")

    async def test_get_worktree_diff_summary_async(self):
        with patch.object(
            SubagentWorktreeManager, "_get_worktree_diff_summary_impl", return_value=("diff", True)
        ):
            out = await SubagentWorktreeManager.get_worktree_diff_summary_async("/p", "/w", "b")
        assert out == ("diff", True)

    async def test_cleanup_worktree_async(self):
        with patch.object(SubagentWorktreeManager, "_cleanup_worktree_impl") as m:
            await SubagentWorktreeManager.cleanup_worktree_async("/p", "/w", "b", keep_branch=True)
        m.assert_called_once_with("/p", "/w", "b", True)


class TestCoverEnsureAvailable:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ensure_missing_project_dir_returns_empty(self):
        session = SimpleNamespace(project_dir="", branch_name="", id="s")
        assert SubagentWorktreeManager.ensure_worktree_available(session) == ""

    def test_ensure_missing_branch_returns_project_dir(self):
        session = SimpleNamespace(project_dir="/proj", branch_name="", id="s")
        assert SubagentWorktreeManager.ensure_worktree_available(session) == "/proj"

    def test_ensure_project_dir_exists_returns_it(self):
        session = SimpleNamespace(project_dir=self.tmp, branch_name="b", id="s")
        assert SubagentWorktreeManager.ensure_worktree_available(session) == self.tmp

    def test_ensure_reattaches_when_missing(self):
        missing = os.path.join(self.tmp, "missing")
        session = SimpleNamespace(project_dir=missing, branch_name="b", id="s")
        with patch.object(SubagentWorktreeManager, "attach_worktree", return_value="/reattached"):
            assert SubagentWorktreeManager.ensure_worktree_available(session, parent_dir="/parent") == "/reattached"

    def test_ensure_reattach_fails_returns_project_dir(self):
        missing = os.path.join(self.tmp, "missing")
        session = SimpleNamespace(project_dir=missing, branch_name="b", id="s")
        with patch.object(SubagentWorktreeManager, "attach_worktree", return_value=None):
            assert (
                SubagentWorktreeManager.ensure_worktree_available(session, parent_dir="/parent") == missing
            )

    def test_ensure_no_parent_returns_project_dir(self):
        missing = os.path.join(self.tmp, "missing2")
        session = SimpleNamespace(project_dir=missing, branch_name="b", id="s")
        assert SubagentWorktreeManager.ensure_worktree_available(session) == missing


class TestCoverEnsureAvailableAsync:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()

    async def test_ensure_worktree_available_async(self):
        session = SimpleNamespace(project_dir=self.tmp, branch_name="b", id="s")
        out = await SubagentWorktreeManager.ensure_worktree_available_async(session, "/p")
        assert out == self.tmp


class TestCoverCleanupFn:
    def test_make_worktree_cleanup_fn_initial(self):
        fn = SubagentWorktreeManager.make_worktree_cleanup_fn("/p", "/w", "b")
        acc = [""]
        with patch.object(
            SubagentWorktreeManager, "append_worktree_diff_to_acc", return_value=(None, None)
        ) as m:
            fn(acc)
        m.assert_called_once_with("/p", "/w", "b", acc, is_followup=False)

    def test_make_worktree_cleanup_fn_followup(self):
        fn = SubagentWorktreeManager.make_worktree_cleanup_fn("/p", "/w", "b", is_followup=True)
        acc = [""]
        with patch.object(
            SubagentWorktreeManager, "append_worktree_diff_to_acc", return_value=(None, None)
        ) as m:
            fn(acc)
        m.assert_called_once_with("/p", "/w", "b", acc, is_followup=True)
