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
        branch_name = f"subagent-{task_id}"

        # Clean up any leftover worktree or branch with same task_id
        SubagentWorktreeManager.cleanup_worktree(project_dir, wt_path, branch_name)

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
    def get_worktree_diff_summary(project_dir: str, wt_path: str, branch_name: str) -> str:
        """Returns git diff summary between worktree branch and project_dir HEAD."""
        if not wt_path or not os.path.exists(wt_path):
            return ""

        try:
            status_res = subprocess.run(
                ["git", "status", "--short"],
                cwd=wt_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            changes = status_res.stdout.strip()
            if not changes:
                return ""

            diff_res = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=wt_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            diff_text = diff_res.stdout.strip()
            if len(diff_text) > 4000:
                diff_text = diff_text[:4000] + "\n... [diff truncated]"
            return f"Status:\n{changes}\n\nDiff:\n{diff_text}"
        except Exception:
            return ""

    @staticmethod
    def cleanup_worktree(project_dir: str, wt_path: str, branch_name: str) -> None:
        """Safely removes git worktree and temporary branch."""
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

            if branch_name:
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
