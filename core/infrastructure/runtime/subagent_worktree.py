import asyncio
import os
import shutil
from typing import Optional, Tuple

from core.infrastructure.platform.paths import WORKTREES_DIR
from core.infrastructure.runtime.git_utils import is_git_repository, run_git


class SubagentWorktreeManager:
    """Manages isolated git worktrees for subagents."""

    @staticmethod
    def is_git_repo(path: str) -> bool:
        if not path or not os.path.exists(path):
            return False
        # Semantically identical to is_git_repository; the exists() guard is kept
        # so early callers skip shelling out to git for dangling paths.
        return is_git_repository(path)

    @staticmethod
    def create_worktree(project_dir: str, session_id: str, branch_name: str) -> Tuple[Optional[str], Optional[str]]:
        """Creates an isolated git worktree for subagent session_id on branch_name.

        If branch_name already exists it attaches the worktree to it; otherwise the
        branch is created from HEAD. Returns (worktree_path, branch_name) on success,
        or (None, None) if unavailable. The branch name is caller-supplied, never
        derived from the session id.

        Sync wrapper around :meth:`_create_worktree_impl`; async callers should use
        :meth:`create_worktree_async` to avoid blocking the event loop.
        """
        return SubagentWorktreeManager._create_worktree_impl(project_dir, session_id, branch_name)

    @staticmethod
    async def create_worktree_async(
        project_dir: str, session_id: str, branch_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Async variant of :meth:`create_worktree`, running git off the event loop."""
        return await asyncio.to_thread(
            SubagentWorktreeManager._create_worktree_impl, project_dir, session_id, branch_name
        )

    @staticmethod
    def _create_worktree_impl(project_dir: str, session_id: str, branch_name: str) -> Tuple[Optional[str], Optional[str]]:
        if not SubagentWorktreeManager.is_git_repo(project_dir) or not branch_name:
            return None, None

        base_worktree_dir = WORKTREES_DIR
        os.makedirs(base_worktree_dir, exist_ok=True)

        wt_path = os.path.join(base_worktree_dir, session_id)

        # Clean up any leftover worktree with same session_id (keep its branch).
        SubagentWorktreeManager.cleanup_worktree(project_dir, wt_path, branch_name, keep_branch=True)

        exists = run_git(["rev-parse", "--verify", f"refs/heads/{branch_name}"], cwd=project_dir, timeout=5)
        if exists.returncode == 0:
            res = run_git(["worktree", "add", wt_path, branch_name], cwd=project_dir, timeout=15)
        else:
            res = run_git(["worktree", "add", "-b", branch_name, wt_path, "HEAD"], cwd=project_dir, timeout=15)
        if res.returncode == 0 and os.path.exists(wt_path):
            return wt_path, branch_name

        return None, None

    @staticmethod
    def attach_worktree(project_dir: str, session_id: str, branch_name: str) -> Optional[str]:
        """Re-attaches a worktree directory to an existing subagent branch for follow-up execution.

        Sync wrapper around :meth:`_attach_worktree_impl`.
        """
        return SubagentWorktreeManager._attach_worktree_impl(project_dir, session_id, branch_name)

    @staticmethod
    def _attach_worktree_impl(project_dir: str, session_id: str, branch_name: str) -> Optional[str]:
        if not SubagentWorktreeManager.is_git_repo(project_dir) or not branch_name:
            return None

        base_worktree_dir = WORKTREES_DIR
        os.makedirs(base_worktree_dir, exist_ok=True)

        wt_path = os.path.join(base_worktree_dir, session_id)
        if os.path.exists(wt_path):
            return wt_path

        res = run_git(["worktree", "add", wt_path, branch_name], cwd=project_dir, timeout=15)
        if res.returncode == 0 and os.path.exists(wt_path):
            return wt_path

        return None

    @staticmethod
    def get_worktree_diff_summary(project_dir: str, wt_path: str, branch_name: str) -> Tuple[str, bool]:
        """Auto-commits changes in worktree and returns (diff_summary, has_changes).

        Sync wrapper around :meth:`_get_worktree_diff_summary_impl`.
        """
        return SubagentWorktreeManager._get_worktree_diff_summary_impl(project_dir, wt_path, branch_name)

    @staticmethod
    async def get_worktree_diff_summary_async(
        project_dir: str, wt_path: str, branch_name: str
    ) -> Tuple[str, bool]:
        """Async variant of :meth:`get_worktree_diff_summary`, running git off the event loop."""
        return await asyncio.to_thread(
            SubagentWorktreeManager._get_worktree_diff_summary_impl, project_dir, wt_path, branch_name
        )

    @staticmethod
    def _get_worktree_diff_summary_impl(project_dir: str, wt_path: str, branch_name: str) -> Tuple[str, bool]:
        if not wt_path or not os.path.exists(wt_path):
            return "", False

        try:
            # Check if there are uncommitted worktree changes
            status_res = run_git(["status", "--short"], cwd=wt_path, timeout=10)
            changes = status_res.stdout.strip()
            if changes:
                # Stage & commit uncommitted worktree changes to the branch with fallback git author config
                run_git(["add", "-A"], cwd=wt_path, timeout=10)
                run_git(
                    [
                        "-c",
                        "user.name=Johnston Subagent",
                        "-c",
                        "user.email=subagent@johnston.local",
                        "commit",
                        "-m",
                        f"subagent: automatic save for {branch_name}",
                    ],
                    cwd=wt_path,
                    timeout=10,
                )

            # Get base commit SHA of main project_dir
            base_sha = "HEAD"
            if project_dir and SubagentWorktreeManager.is_git_repo(project_dir):
                base_res = run_git(["rev-parse", "HEAD"], cwd=project_dir, timeout=5)
                if base_res.returncode == 0 and base_res.stdout.strip():
                    base_sha = base_res.stdout.strip()

            # Diff worktree against parent project_dir base commit
            diff_res = run_git(["diff", base_sha], cwd=wt_path, timeout=10)
            diff_text = diff_res.stdout.strip()
            if not diff_text:
                return "", False

            if len(diff_text) > 4000:
                diff_text = diff_text[:4000] + "\n... [diff truncated]"

            status_block = f"Status:\n{changes}\n\n" if changes else ""
            return f"{status_block}Diff:\n{diff_text}", True
        except Exception:
            return "", False

    @staticmethod
    def cleanup_worktree(project_dir: str, wt_path: str, branch_name: str, keep_branch: bool = False) -> None:
        """Safely removes git worktree and optionally deletes the branch if empty.

        Sync wrapper around :meth:`_cleanup_worktree_impl`.
        """
        SubagentWorktreeManager._cleanup_worktree_impl(project_dir, wt_path, branch_name, keep_branch)

    @staticmethod
    async def cleanup_worktree_async(
        project_dir: str, wt_path: str, branch_name: str, keep_branch: bool = False
    ) -> None:
        """Async variant of :meth:`cleanup_worktree`, running git off the event loop."""
        await asyncio.to_thread(
            SubagentWorktreeManager._cleanup_worktree_impl, project_dir, wt_path, branch_name, keep_branch
        )

    @staticmethod
    def _cleanup_worktree_impl(
        project_dir: str, wt_path: str, branch_name: str, keep_branch: bool = False
    ) -> None:
        if project_dir and SubagentWorktreeManager.is_git_repo(project_dir):
            if wt_path:
                run_git(["worktree", "remove", "--force", wt_path], cwd=project_dir, timeout=10)

            if branch_name and not keep_branch:
                run_git(["branch", "-D", branch_name], cwd=project_dir, timeout=10)

        if wt_path and os.path.exists(wt_path):
            try:
                shutil.rmtree(wt_path, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def ensure_worktree_available(session, parent_dir: Optional[str] = None) -> str:
        """Return a working project_dir for a subagent, re-attaching its worktree
        if it was removed (e.g. after a process restart). Returns the live path.

        Encapsulates the re-attach check so tool callers don't poke at
        ``os.path`` / worktree plumbing directly.
        """
        project_dir = getattr(session, "project_dir", "") or ""
        branch_name = getattr(session, "branch_name", "") or ""
        if not project_dir or not branch_name:
            return project_dir
        if os.path.isdir(project_dir):
            return project_dir
        reattached = None
        if parent_dir:
            reattached = SubagentWorktreeManager.attach_worktree(parent_dir, session.id, branch_name)
        if reattached:
            return reattached
        return project_dir

    @staticmethod
    async def ensure_worktree_available_async(session, parent_dir: Optional[str] = None) -> str:
        """Async variant of :meth:`ensure_worktree_available`, running git off the event loop."""
        return await asyncio.to_thread(SubagentWorktreeManager.ensure_worktree_available, session, parent_dir)

    @staticmethod
    def make_worktree_cleanup_fn(parent_dir: str, wt_path: Optional[str], wt_branch: Optional[str], is_followup: bool = False):
        """Builds a cleanup callback that appends the worktree diff to acc and
        removes the worktree. Shared by invoke_subagent and manage_subagent so
        the follow-up vs initial-spawn handling stays in one place.

        Mirrors the historical contract: for initial spawns append_worktree_diff_to_acc
        returns the (possibly recreated) worktree paths, for follow-ups it mutates
        session paths on disk directly.
        """
        if is_followup:
            def _cleanup_followup(acc):
                SubagentWorktreeManager.append_worktree_diff_to_acc(
                    parent_dir, wt_path, wt_branch, acc, is_followup=True
                )
            return _cleanup_followup

        def _cleanup_worktree_and_append_diff(acc):
            nonlocal wt_path, wt_branch
            wt_path, wt_branch = SubagentWorktreeManager.append_worktree_diff_to_acc(
                parent_dir, wt_path, wt_branch, acc, is_followup=False
            )
        return _cleanup_worktree_and_append_diff

    @staticmethod
    def append_worktree_diff_to_acc(
        parent_dir: str,
        wt_path: Optional[str],
        wt_branch: Optional[str],
        acc: list[str],
        is_followup: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Collects worktree diff summary, appends diff text to acc, and cleans up worktree."""
        if wt_path and wt_branch and os.path.isdir(wt_path):
            diff_text, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(parent_dir, wt_path, wt_branch)
            if has_changes and diff_text:
                if is_followup:
                    acc[0] = acc[0].rstrip() + (
                        f"\n\n[Worktree Branch '{wt_branch}']\n"
                        f"Changes updated on branch '{wt_branch}'. Run `git merge {wt_branch}` to apply.\n"
                        f"After merging, ask the user via the `ask_user` tool whether to delete the subagent-created branch '{wt_branch}' before continuing.\n\n"
                        f"{diff_text}"
                    )
                else:
                    acc[0] += (
                        f"\n\n[Worktree Branch '{wt_branch}']\n"
                        f"Changes saved to git branch '{wt_branch}'. Run `git merge {wt_branch}` to apply, or `git diff {wt_branch}` for full diff.\n"
                        f"After merging, clean up the branch with `git branch -d {wt_branch}`.\n\n"
                        f"{diff_text}"
                    )
            keep_b = True if is_followup else has_changes
            SubagentWorktreeManager.cleanup_worktree(parent_dir, wt_path, wt_branch, keep_branch=keep_b)
            return None, None
        return wt_path, wt_branch
