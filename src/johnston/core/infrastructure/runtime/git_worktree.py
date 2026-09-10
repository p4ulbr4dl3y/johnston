"""Git Worktree Manager for Johnston.

Provides unified management of isolated git worktrees, branch listing,
dry-run merge conflict detection via git merge-tree, clean merges, and worktree cleanup.
"""

import asyncio
import os
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple

from johnston.core.infrastructure.platform.paths import WORKTREES_DIR
from johnston.core.infrastructure.runtime.git_utils import is_git_repository, run_git


class GitWorktreeManager:
    """Manages isolated git worktrees for Johnston."""

    @staticmethod
    def is_git_repo(path: str) -> bool:
        """Returns True if path exists and is inside a git working tree."""
        if not path or not os.path.exists(path):
            return False
        return is_git_repository(path)

    @staticmethod
    def get_repo_root(project_dir: str) -> str:
        """Returns the realpath of the git repository toplevel root, or empty string."""
        if not project_dir or not os.path.exists(project_dir):
            return ""
        res = run_git(["rev-parse", "--show-toplevel"], cwd=project_dir, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            return os.path.realpath(res.stdout.strip())
        return ""

    @staticmethod
    async def get_repo_root_async(project_dir: str) -> str:
        """Async variant of get_repo_root."""
        return await asyncio.to_thread(GitWorktreeManager.get_repo_root, project_dir)

    @staticmethod
    def sanitize_branch_name(branch_name: str) -> str:
        """Sanitizes branch name into a safe directory name."""
        slug = re.sub(r"[^\w.-]", "-", branch_name)
        slug = re.sub(r"-+", "-", slug).strip(".-")
        return slug or "worktree"

    @staticmethod
    def get_worktree_path(project_dir: str, branch_name: str) -> str:
        """Returns the deterministic worktree path ~/.johnston/worktrees/<repo_name>/<sanitized_branch>."""
        repo_root = GitWorktreeManager.get_repo_root(project_dir) or project_dir
        repo_name = os.path.basename(os.path.normpath(repo_root)) or "repo"
        sanitized = GitWorktreeManager.sanitize_branch_name(branch_name)
        return os.path.join(WORKTREES_DIR, repo_name, sanitized)

    @staticmethod
    def is_secret_file(filename: str) -> bool:
        """Returns True if filename or path matches known secret/credential patterns."""
        base = os.path.basename(filename).lower()
        if base == ".env" or base.startswith(".env.") or base.endswith(".env"):
            return True
        secret_exts = (".pem", ".key", ".pfx", ".p12", ".pkcs12")
        if any(base.endswith(ext) for ext in secret_exts):
            return True
        secret_tokens = ("credentials", "id_rsa", "id_ed25519", "secret", "token")
        if any(tok in base for tok in secret_tokens):
            return True
        return False

    @staticmethod
    def list_branches_and_worktrees(project_dir: str) -> List[Dict[str, Any]]:
        """Returns list of branches and worktrees with keys:
        name, is_current, is_worktree, is_root, path.
        """
        if not GitWorktreeManager.is_git_repo(project_dir):
            return []
        repo_root = GitWorktreeManager.get_repo_root(project_dir)
        if not repo_root:
            return []

        # Current top-level worktree or root for project_dir
        current_toplevel = GitWorktreeManager.get_repo_root(project_dir)

        # 1. Parse active worktrees via git worktree list --porcelain
        wt_res = run_git(["worktree", "list", "--porcelain"], cwd=repo_root, timeout=10)
        worktrees: List[Dict[str, Any]] = []
        current_entry: Dict[str, Any] = {}
        for line in wt_res.stdout.splitlines():
            line = line.strip()
            if not line:
                if current_entry:
                    worktrees.append(current_entry)
                    current_entry = {}
                continue
            if line.startswith("worktree "):
                current_entry["path"] = line[9:].strip()
            elif line.startswith("HEAD "):
                current_entry["head"] = line[5:].strip()
            elif line.startswith("branch "):
                ref = line[7:].strip()
                if ref.startswith("refs/heads/"):
                    current_entry["branch"] = ref[len("refs/heads/") :]
                else:
                    current_entry["branch"] = ref
            elif line == "detached":
                current_entry["detached"] = True
        if current_entry:
            worktrees.append(current_entry)

        # 2. Get all local branches
        branch_res = run_git(
            ["for-each-ref", "--format=%(refname:short)", "refs/heads/"],
            cwd=repo_root,
            timeout=10,
        )
        all_local_branches = [b.strip() for b in branch_res.stdout.splitlines() if b.strip()]

        items: List[Dict[str, Any]] = []
        seen_branches: set[str] = set()

        # Add active worktrees
        for wt in worktrees:
            wt_path = wt.get("path", "")
            real_wt_path = os.path.realpath(wt_path)
            is_root = real_wt_path == os.path.realpath(repo_root)
            branch_name = wt.get("branch")
            if not branch_name:
                head = wt.get("head", "")[:7]
                branch_name = f"detached HEAD ({head})" if head else "detached"

            seen_branches.add(branch_name)
            is_current = real_wt_path == os.path.realpath(current_toplevel)
            items.append(
                {
                    "name": branch_name,
                    "is_current": is_current,
                    "is_worktree": not is_root,
                    "is_root": is_root,
                    "path": wt_path,
                }
            )

        # Add local branches without worktree
        for branch in all_local_branches:
            if branch in seen_branches:
                continue
            seen_branches.add(branch)
            items.append(
                {
                    "name": branch,
                    "is_current": False,
                    "is_worktree": False,
                    "is_root": False,
                    "path": "",
                }
            )

        # Deterministic sorting: current first, root second, worktrees third, local fourth
        items.sort(key=lambda x: (not x["is_current"], not x["is_root"], not x["is_worktree"], x["name"]))
        return items

    @staticmethod
    async def list_branches_and_worktrees_async(project_dir: str) -> List[Dict[str, Any]]:
        """Async variant of list_branches_and_worktrees."""
        return await asyncio.to_thread(GitWorktreeManager.list_branches_and_worktrees, project_dir)

    @staticmethod
    def create_worktree(
        project_dir: str, branch_name: str, base_branch: str = "HEAD"
    ) -> Tuple[Optional[str], Optional[str]]:
        """Creates a git worktree at ~/.johnston/worktrees/<repo>/<branch>.

        Returns (wt_path, branch_name) on success, (None, None) on failure.
        """
        if not GitWorktreeManager.is_git_repo(project_dir) or not branch_name:
            return None, None
        repo_root = GitWorktreeManager.get_repo_root(project_dir)
        if not repo_root:
            return None, None

        wt_path = GitWorktreeManager.get_worktree_path(repo_root, branch_name)
        os.makedirs(os.path.dirname(wt_path), exist_ok=True)

        if os.path.exists(wt_path):
            if GitWorktreeManager.is_git_repo(wt_path):
                return wt_path, branch_name
            GitWorktreeManager.remove_worktree(repo_root, wt_path, keep_branch=True)

        from johnston.core.infrastructure.config.settings import get_settings

        try:
            wt_timeout = get_settings().subagents.worktree_timeout
        except Exception:
            wt_timeout = 15.0

        exists = run_git(["rev-parse", "--verify", f"refs/heads/{branch_name}"], cwd=repo_root, timeout=5)
        if exists.returncode == 0:
            res = run_git(["worktree", "add", wt_path, branch_name], cwd=repo_root, timeout=wt_timeout)
        else:
            base = base_branch or "HEAD"
            res = run_git(["worktree", "add", "-b", branch_name, wt_path, base], cwd=repo_root, timeout=wt_timeout)

        if res.returncode == 0 and os.path.exists(wt_path):
            return wt_path, branch_name

        return None, None

    @staticmethod
    async def create_worktree_async(
        project_dir: str, branch_name: str, base_branch: str = "HEAD"
    ) -> Tuple[Optional[str], Optional[str]]:
        """Async variant of create_worktree."""
        return await asyncio.to_thread(
            GitWorktreeManager.create_worktree, project_dir, branch_name, base_branch
        )

    @staticmethod
    def attach_worktree(project_dir: str, branch_name: str) -> Optional[str]:
        """Attaches to existing worktree or creates a worktree for existing branch."""
        if not GitWorktreeManager.is_git_repo(project_dir) or not branch_name:
            return None
        repo_root = GitWorktreeManager.get_repo_root(project_dir)
        if not repo_root:
            return None

        wt_path = GitWorktreeManager.get_worktree_path(repo_root, branch_name)
        if os.path.exists(wt_path) and GitWorktreeManager.is_git_repo(wt_path):
            return wt_path

        GitWorktreeManager.remove_worktree(repo_root, wt_path, keep_branch=True)
        os.makedirs(os.path.dirname(wt_path), exist_ok=True)

        from johnston.core.infrastructure.config.settings import get_settings

        try:
            wt_timeout = get_settings().subagents.worktree_timeout
        except Exception:
            wt_timeout = 15.0

        exists = run_git(["rev-parse", "--verify", f"refs/heads/{branch_name}"], cwd=repo_root, timeout=5)
        if exists.returncode == 0:
            res = run_git(["worktree", "add", wt_path, branch_name], cwd=repo_root, timeout=wt_timeout)
        else:
            res = run_git(["worktree", "add", "-b", branch_name, wt_path, "HEAD"], cwd=repo_root, timeout=wt_timeout)

        if res.returncode == 0 and os.path.exists(wt_path):
            return wt_path

        return None

    @staticmethod
    async def attach_worktree_async(project_dir: str, branch_name: str) -> Optional[str]:
        """Async variant of attach_worktree."""
        return await asyncio.to_thread(GitWorktreeManager.attach_worktree, project_dir, branch_name)

    @staticmethod
    def check_merge_conflicts(
        project_dir: str, source_branch: str, target_branch: str
    ) -> Tuple[bool, List[str]]:
        """Uses git merge-tree to check for merge conflicts without altering working directory.

        Returns (has_conflicts, conflict_files).
        """
        if not GitWorktreeManager.is_git_repo(project_dir):
            return True, ["Not a git repository"]
        if not source_branch or source_branch.startswith("detached"):
            return True, [f"Invalid source branch: '{source_branch}'"]
        if not target_branch or target_branch.startswith("detached"):
            return True, [f"Invalid target branch: '{target_branch}'"]
        if source_branch == target_branch:
            return False, []

        repo_root = GitWorktreeManager.get_repo_root(project_dir) or project_dir
        res = run_git(
            ["merge-tree", "--write-tree", "--name-only", target_branch, source_branch],
            cwd=repo_root,
            timeout=15,
        )
        if res.returncode == 0:
            return False, []

        conflicts: List[str] = []
        lines = res.stdout.strip().splitlines()
        if len(lines) > 1:
            for line in lines[1:]:
                line = line.strip()
                if not line:
                    break
                conflicts.append(line)

        if not conflicts:
            for line in lines:
                if "CONFLICT" in line:
                    conflicts.append(line.strip())

        if res.returncode != 1 and not conflicts:
            err = res.stderr.strip() or res.stdout.strip() or f"git merge-tree exit code {res.returncode}"
            return True, [err]

        return True, conflicts or ["Unspecified merge conflict"]

    @staticmethod
    async def check_merge_conflicts_async(
        project_dir: str, source_branch: str, target_branch: str
    ) -> Tuple[bool, List[str]]:
        """Async variant of check_merge_conflicts."""
        return await asyncio.to_thread(
            GitWorktreeManager.check_merge_conflicts, project_dir, source_branch, target_branch
        )

    @staticmethod
    def merge_branch(project_dir: str, source_branch: str, target_branch: str) -> Tuple[bool, str]:
        """Merges source_branch into target_branch after checking for conflicts.

        Returns (success, message).
        """
        if not GitWorktreeManager.is_git_repo(project_dir):
            return False, "Not a git repository"
        if not source_branch or source_branch.startswith("detached"):
            return False, f"Invalid source branch: '{source_branch}'"
        if not target_branch or target_branch.startswith("detached"):
            return False, f"Invalid target branch: '{target_branch}'"

        repo_root = GitWorktreeManager.get_repo_root(project_dir) or project_dir

        has_conflicts, conflict_files = GitWorktreeManager.check_merge_conflicts(
            repo_root, source_branch, target_branch
        )
        if has_conflicts:
            files_str = ", ".join(conflict_files)
            return False, f"Merge conflicts detected in: {files_str}"

        wt_list = GitWorktreeManager.list_branches_and_worktrees(repo_root)
        target_entry = next((e for e in wt_list if e["name"] == target_branch and e.get("path")), None)
        if target_entry and target_entry.get("path"):
            merge_cwd = target_entry["path"]
        else:
            wt_path, _ = GitWorktreeManager.create_worktree(repo_root, target_branch)
            if not wt_path:
                return False, f"Cannot merge: target branch '{target_branch}' is not checked out and failed to create worktree."
            merge_cwd = wt_path

        cur_head = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=merge_cwd, timeout=5)
        if cur_head.returncode != 0 or cur_head.stdout.strip() != target_branch:
            return False, f"Target directory '{merge_cwd}' is on branch '{cur_head.stdout.strip()}', expected '{target_branch}'."

        res = run_git(["merge", "--no-edit", source_branch], cwd=merge_cwd, timeout=30)
        if res.returncode == 0:
            return True, f"Successfully merged '{source_branch}' into '{target_branch}'."

        err = res.stderr.strip() or res.stdout.strip() or f"git merge exit code {res.returncode}"
        return False, f"Merge failed: {err}"

    @staticmethod
    async def merge_branch_async(
        project_dir: str, source_branch: str, target_branch: str
    ) -> Tuple[bool, str]:
        """Async variant of merge_branch."""
        return await asyncio.to_thread(
            GitWorktreeManager.merge_branch, project_dir, source_branch, target_branch
        )

    @staticmethod
    def remove_worktree(
        project_dir: str,
        wt_path: str,
        branch_name: str = "",
        delete_branch: bool = False,
        keep_branch: bool = True,
    ) -> bool:
        """Removes worktree and optionally deletes branch."""
        repo_root = GitWorktreeManager.get_repo_root(project_dir) or project_dir
        if repo_root and GitWorktreeManager.is_git_repo(repo_root):
            if wt_path:
                run_git(["worktree", "remove", "--force", wt_path], cwd=repo_root, timeout=10)
            if branch_name and (delete_branch or not keep_branch):
                run_git(["branch", "-D", branch_name], cwd=repo_root, timeout=10)
            run_git(["worktree", "prune"], cwd=repo_root, timeout=5)

        if wt_path and os.path.exists(wt_path):
            try:
                shutil.rmtree(wt_path, ignore_errors=True)
            except Exception:
                pass

        return not (wt_path and os.path.exists(wt_path))

    @staticmethod
    async def remove_worktree_async(
        project_dir: str,
        wt_path: str,
        branch_name: str = "",
        delete_branch: bool = False,
        keep_branch: bool = True,
    ) -> bool:
        """Async variant of remove_worktree."""
        return await asyncio.to_thread(
            GitWorktreeManager.remove_worktree,
            project_dir,
            wt_path,
            branch_name,
            delete_branch,
            keep_branch,
        )
