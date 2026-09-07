"""Unit tests for GitWorktreeManager."""

import os
import subprocess
import tempfile
import unittest

import pytest

from core.application.generation.prompt_builder import PromptBuilder
from core.infrastructure.runtime.git_worktree import GitWorktreeManager


class TestGitWorktreeManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(self.temp_dir.name)

        # Initialize test git repository
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        )

        dummy_file = os.path.join(self.repo_dir, "README.md")
        with open(dummy_file, "w", encoding="utf-8") as f:
            f.write("# Initial Main\n")

        subprocess.run(["git", "add", "."], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.repo_dir, capture_output=True, text=True)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_is_git_repo(self):
        self.assertTrue(GitWorktreeManager.is_git_repo(self.repo_dir))
        self.assertFalse(GitWorktreeManager.is_git_repo(""))
        self.assertFalse(GitWorktreeManager.is_git_repo("/non/existent/path/here"))

        with tempfile.TemporaryDirectory() as empty_dir:
            self.assertFalse(GitWorktreeManager.is_git_repo(empty_dir))

    def test_get_repo_root(self):
        self.assertEqual(GitWorktreeManager.get_repo_root(self.repo_dir), self.repo_dir)

        sub_dir = os.path.join(self.repo_dir, "sub", "folder")
        os.makedirs(sub_dir, exist_ok=True)
        self.assertEqual(GitWorktreeManager.get_repo_root(sub_dir), self.repo_dir)

        with tempfile.TemporaryDirectory() as empty_dir:
            self.assertEqual(GitWorktreeManager.get_repo_root(empty_dir), "")

    def test_sanitize_branch_name(self):
        self.assertEqual(GitWorktreeManager.sanitize_branch_name("main"), "main")
        self.assertEqual(GitWorktreeManager.sanitize_branch_name("feature/add-login"), "feature-add-login")
        self.assertEqual(GitWorktreeManager.sanitize_branch_name("fix/issue#42:bug"), "fix-issue-42-bug")
        self.assertEqual(GitWorktreeManager.sanitize_branch_name("---"), "worktree")

    def test_get_worktree_path(self):
        path = GitWorktreeManager.get_worktree_path(self.repo_dir, "feat/my-branch")
        repo_name = os.path.basename(self.repo_dir)
        self.assertTrue(path.endswith(os.path.join(repo_name, "feat-my-branch")))

    def test_create_worktree_with_symlinks_and_cleanup(self):
        # Create .env and .venv in repo root
        env_file = os.path.join(self.repo_dir, ".env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("SECRET=xyz\n")

        venv_dir = os.path.join(self.repo_dir, ".venv")
        os.makedirs(venv_dir, exist_ok=True)

        branch_name = "feat/test-create-wt"
        wt_path, created_branch = GitWorktreeManager.create_worktree(self.repo_dir, branch_name)

        try:
            self.assertIsNotNone(wt_path)
            self.assertEqual(created_branch, branch_name)
            self.assertTrue(os.path.isdir(wt_path))

            # Verify symlinks
            wt_env = os.path.join(wt_path, ".env")
            wt_venv = os.path.join(wt_path, ".venv")
            self.assertTrue(os.path.islink(wt_env))
            self.assertTrue(os.path.islink(wt_venv))

            # Modify file in worktree
            wt_readme = os.path.join(wt_path, "README.md")
            with open(wt_readme, "a", encoding="utf-8") as f:
                f.write("Worktree edit\n")

            # Remove worktree keeping branch
            res = GitWorktreeManager.remove_worktree(self.repo_dir, wt_path, branch_name, delete_branch=False)
            self.assertTrue(res)
            self.assertFalse(os.path.exists(wt_path))

            # Branch still exists in repo
            branch_check = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{branch_name}"],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
            )
            self.assertEqual(branch_check.returncode, 0)
        finally:
            if wt_path and os.path.exists(wt_path):
                GitWorktreeManager.remove_worktree(self.repo_dir, wt_path, branch_name, delete_branch=True)

    def test_create_worktree_existing_branch(self):
        # Create a branch first
        subprocess.run(["git", "branch", "existing-branch"], cwd=self.repo_dir, capture_output=True, text=True)

        wt_path, created_branch = GitWorktreeManager.create_worktree(self.repo_dir, "existing-branch")
        try:
            self.assertIsNotNone(wt_path)
            self.assertEqual(created_branch, "existing-branch")
            self.assertTrue(os.path.isdir(wt_path))
        finally:
            if wt_path:
                GitWorktreeManager.remove_worktree(self.repo_dir, wt_path, "existing-branch", delete_branch=True)

    def test_attach_worktree(self):
        branch = "attach-branch"
        wt_path = GitWorktreeManager.attach_worktree(self.repo_dir, branch)
        try:
            self.assertIsNotNone(wt_path)
            self.assertTrue(os.path.isdir(wt_path))

            # Calling attach again on existing worktree should return same path
            wt_path_second = GitWorktreeManager.attach_worktree(self.repo_dir, branch)
            self.assertEqual(wt_path, wt_path_second)
        finally:
            if wt_path:
                GitWorktreeManager.remove_worktree(self.repo_dir, wt_path, branch, delete_branch=True)

    def test_list_branches_and_worktrees(self):
        # Create one branch without worktree
        subprocess.run(["git", "branch", "local-only"], cwd=self.repo_dir, capture_output=True, text=True)

        # Create one worktree
        wt_branch = "active-wt"
        wt_path, _ = GitWorktreeManager.create_worktree(self.repo_dir, wt_branch)

        try:
            entries = GitWorktreeManager.list_branches_and_worktrees(self.repo_dir)

            names = [e["name"] for e in entries]
            self.assertIn("main", names)
            self.assertIn("local-only", names)
            self.assertIn(wt_branch, names)

            # Check root entry
            root_entry = next(e for e in entries if e["name"] == "main")
            self.assertTrue(root_entry["is_root"])
            self.assertFalse(root_entry["is_worktree"])
            self.assertTrue(root_entry["is_current"])
            self.assertEqual(os.path.realpath(root_entry["path"]), self.repo_dir)

            # Check worktree entry
            wt_entry = next(e for e in entries if e["name"] == wt_branch)
            self.assertFalse(wt_entry["is_root"])
            self.assertTrue(wt_entry["is_worktree"])
            self.assertFalse(wt_entry["is_current"])
            self.assertEqual(os.path.realpath(wt_entry["path"]), os.path.realpath(wt_path))

            # Check local branch entry
            local_entry = next(e for e in entries if e["name"] == "local-only")
            self.assertFalse(local_entry["is_root"])
            self.assertFalse(local_entry["is_worktree"])
            self.assertFalse(local_entry["is_current"])
            self.assertEqual(local_entry["path"], "")
        finally:
            if wt_path:
                GitWorktreeManager.remove_worktree(self.repo_dir, wt_path, wt_branch, delete_branch=True)

    def test_check_merge_conflicts_and_merge_branch(self):
        # 1. Clean branch merge
        wt_clean, b_clean = GitWorktreeManager.create_worktree(self.repo_dir, "feature-clean")
        try:
            with open(os.path.join(wt_clean, "new_feature.py"), "w", encoding="utf-8") as f:
                f.write("def feat(): pass\n")
            subprocess.run(["git", "add", "."], cwd=wt_clean, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "add feat"], cwd=wt_clean, capture_output=True, text=True)

            has_conflicts, conflict_files = GitWorktreeManager.check_merge_conflicts(
                self.repo_dir, b_clean, "main"
            )
            self.assertFalse(has_conflicts)
            self.assertEqual(conflict_files, [])

            # Perform merge
            ok, msg = GitWorktreeManager.merge_branch(self.repo_dir, b_clean, "main")
            self.assertTrue(ok)
            self.assertIn("Successfully merged", msg)
            self.assertTrue(os.path.exists(os.path.join(self.repo_dir, "new_feature.py")))
        finally:
            GitWorktreeManager.remove_worktree(self.repo_dir, wt_clean, b_clean, delete_branch=True)

        # 2. Conflicting branch merge
        wt_conflict, b_conflict = GitWorktreeManager.create_worktree(self.repo_dir, "feature-conflict")
        try:
            # Change README in worktree
            with open(os.path.join(wt_conflict, "README.md"), "w", encoding="utf-8") as f:
                f.write("# Conflict in worktree\n")
            subprocess.run(["git", "add", "."], cwd=wt_conflict, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "wt commit"], cwd=wt_conflict, capture_output=True, text=True)

            # Change README in main repo
            with open(os.path.join(self.repo_dir, "README.md"), "w", encoding="utf-8") as f:
                f.write("# Conflict in main repo\n")
            subprocess.run(["git", "add", "."], cwd=self.repo_dir, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "main commit"], cwd=self.repo_dir, capture_output=True, text=True)

            has_conflicts, conflict_files = GitWorktreeManager.check_merge_conflicts(
                self.repo_dir, b_conflict, "main"
            )
            self.assertTrue(has_conflicts)
            self.assertTrue(any("README.md" in c for c in conflict_files))

            # Attempt merge should fail cleanly
            ok, msg = GitWorktreeManager.merge_branch(self.repo_dir, b_conflict, "main")
            self.assertFalse(ok)
            self.assertIn("Merge conflicts detected", msg)
        finally:
            GitWorktreeManager.remove_worktree(self.repo_dir, wt_conflict, b_conflict, delete_branch=True)

    def test_remove_worktree_deletes_branch(self):
        wt_path, b_name = GitWorktreeManager.create_worktree(self.repo_dir, "delete-me")
        self.assertTrue(os.path.isdir(wt_path))

        ok = GitWorktreeManager.remove_worktree(self.repo_dir, wt_path, b_name, delete_branch=True)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(wt_path))

        check = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{b_name}"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(check.returncode, 0)


@pytest.mark.asyncio
class TestGitWorktreeAsync:
    async def test_async_operations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = os.path.realpath(temp_dir)
            subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo_dir, capture_output=True, text=True)
            with open(os.path.join(repo_dir, "f.txt"), "w") as f:
                f.write("test")
            subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, capture_output=True, text=True)

            root = await GitWorktreeManager.get_repo_root_async(repo_dir)
            assert root == repo_dir

            wt_path, branch = await GitWorktreeManager.create_worktree_async(repo_dir, "async-branch")
            assert wt_path is not None
            assert branch == "async-branch"

            entries = await GitWorktreeManager.list_branches_and_worktrees_async(repo_dir)
            assert any(e["name"] == "async-branch" for e in entries)

            has_conflicts, conflicts = await GitWorktreeManager.check_merge_conflicts_async(
                repo_dir, "async-branch", "main"
            )
            assert not has_conflicts
            assert conflicts == []

            ok, msg = await GitWorktreeManager.merge_branch_async(repo_dir, "async-branch", "main")
            assert ok

            removed = await GitWorktreeManager.remove_worktree_async(
                repo_dir, wt_path, "async-branch", delete_branch=True
            )
            assert removed


class TestPromptBuilderWorktreeCaching:
    def test_main_agent_worktree_prompt_inclusion(self):
        """Verify that main agent (is_subagent=False) includes worktree prompt when worktree_branch is set."""
        builder = PromptBuilder(
            "Base system prompt",
            [],
            role="worker",
            is_subagent=False,
            worktree_branch="feat-main-wt",
        )
        prompt = builder.build_system_prompt()
        assert "<worktree>" in prompt
        assert "Branch: `feat-main-wt`" in prompt
        assert "Do NOT `git checkout/switch`, merge, or push." in prompt

    def test_worktree_placed_at_tail_of_stable_core(self):
        """Verify that <worktree> snippet is placed at the end of stable_core, before <environment>."""
        builder = PromptBuilder(
            "Base prompt",
            [],
            role="worker",
            worktree_branch="my-branch",
        )
        prompt = builder.build_system_prompt()
        wt_idx = prompt.index("<worktree>")
        env_idx = prompt.index("<environment>")
        assert wt_idx < env_idx

        # Check that rules/skills precede worktree
        if "<system_rules>" in prompt:
            rules_idx = prompt.index("<system_rules>")
            assert rules_idx < wt_idx
