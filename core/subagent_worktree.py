import os
import shutil
import subprocess
from typing import Optional, Tuple


class SubagentWorktreeManager:
    """Manages isolated git worktrees for subagents."""

    @staticmethod
    def is_git_repo(path: str) -> bool:
        if not path or not os.path.exists(path):
            return False
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.returncode == 0 and res.stdout.strip() == "true"
        except Exception:
            return False

    @staticmethod
    def create_worktree(project_dir: str, task_id: str) -> Tuple[Optional[str], Optional[str]]:
        """Creates an isolated git worktree and branch for subagent task_id.

        Returns (worktree_path, branch_name) on success, or (None, None) if unavailable.
        """
        if not SubagentWorktreeManager.is_git_repo(project_dir):
            return None, None

        base_worktree_dir = os.path.expanduser("~/.johnston/worktrees")
        os.makedirs(base_worktree_dir, exist_ok=True)

        wt_path = os.path.join(base_worktree_dir, task_id)
        branch_name = task_id if task_id.startswith("subagent-") else f"subagent-{task_id}"

        # Clean up any leftover worktree or branch with same task_id
        SubagentWorktreeManager.cleanup_worktree(project_dir, wt_path, branch_name, keep_branch=False)

        try:
            res = subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, wt_path, "HEAD"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0 and os.path.exists(wt_path):
                return wt_path, branch_name
        except Exception:
            pass

        return None, None

    @staticmethod
    def attach_worktree(project_dir: str, task_id: str, branch_name: str) -> Optional[str]:
        """Re-attaches a worktree directory to an existing subagent branch for follow-up execution."""
        if not SubagentWorktreeManager.is_git_repo(project_dir) or not branch_name:
            return None

        base_worktree_dir = os.path.expanduser("~/.johnston/worktrees")
        os.makedirs(base_worktree_dir, exist_ok=True)

        wt_path = os.path.join(base_worktree_dir, task_id)
        if os.path.exists(wt_path):
            return wt_path

        try:
            res = subprocess.run(
                ["git", "worktree", "add", wt_path, branch_name],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0 and os.path.exists(wt_path):
                return wt_path
        except Exception:
            pass

        return None

    @staticmethod
    def get_worktree_diff_summary(project_dir: str, wt_path: str, branch_name: str) -> Tuple[str, bool]:
        """Auto-commits changes in worktree and returns (diff_summary, has_changes)."""
        if not wt_path or not os.path.exists(wt_path):
            return "", False

        try:
            # Check if there are uncommitted worktree changes
            status_res = subprocess.run(
                ["git", "status", "--short"],
                cwd=wt_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            changes = status_res.stdout.strip()
            if changes:
                # Stage & commit uncommitted worktree changes to the branch with fallback git author config
                subprocess.run(["git", "add", "-A"], cwd=wt_path, capture_output=True, text=True, timeout=10)
                subprocess.run(
                    [
                        "git",
                        "-c", "user.name=Johnston Subagent",
                        "-c", "user.email=subagent@johnston.local",
                        "commit",
                        "-m", f"subagent: automatic save for {branch_name}",
                    ],
                    cwd=wt_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

            # Get base commit SHA of main project_dir
            base_sha = "HEAD"
            if project_dir and SubagentWorktreeManager.is_git_repo(project_dir):
                base_res = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if base_res.returncode == 0 and base_res.stdout.strip():
                    base_sha = base_res.stdout.strip()

            # Diff worktree against parent project_dir base commit
            diff_res = subprocess.run(
                ["git", "diff", base_sha],
                cwd=wt_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
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
        """Safely removes git worktree and optionally deletes the branch if empty."""
        if project_dir and SubagentWorktreeManager.is_git_repo(project_dir):
            if wt_path:
                try:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", wt_path],
                        cwd=project_dir,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except Exception:
                    pass

            if branch_name and not keep_branch:
                try:
                    subprocess.run(
                        ["git", "branch", "-D", branch_name],
                        cwd=project_dir,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except Exception:
                    pass

        if wt_path and os.path.exists(wt_path):
            try:
                shutil.rmtree(wt_path, ignore_errors=True)
            except Exception:
                pass

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
                        f"After merging, ask the user via the ask_user tool whether to delete the subagent-created branch '{wt_branch}' before continuing.\n\n"
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

