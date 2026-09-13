"""Git bridge adapters between TUI and core."""
from __future__ import annotations

from typing import Any

from johnston.core.infrastructure.platform.paths import WORKTREES_DIR
from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager

__all__ = [
    "GitWorktreeManager",
    "WORKTREES_DIR",
    "get_branch_info",
    "get_diff_stats",
    "get_git_worktree_manager",
    "get_ignore_dirs",
    "list_branches_and_worktrees",
    "make_git_diff",
    "worktrees_dir",
]


def worktrees_dir() -> str:
    """Resolve the worktrees directory live from core paths (test-overridable)."""
    import johnston.core.infrastructure.platform.paths as _m

    return getattr(_m, "WORKTREES_DIR", "") or ""


def get_branch_info(cwd: str | None = None) -> Any:
    """Detect the current git branch (core git metrics helper)."""
    from johnston.core.infrastructure.platform.git_metrics import get_branch_info as _f

    return _f(cwd)


def get_diff_stats(cwd: str | None = None) -> Any:
    """Compute '+add/-del' diff stats vs HEAD (core git metrics helper)."""
    from johnston.core.infrastructure.platform.git_metrics import get_diff_stats as _f

    return _f(cwd)


def make_git_diff(
    old_content: str,
    new_content: str,
    *,
    fromfile: str = "file",
    tofile: str = "file",
    context: int = 3,
) -> str:
    """Generate a unified diff for two content strings (core git helper)."""
    from johnston.core.infrastructure.runtime.git_utils import make_git_diff as _f

    return _f(old_content, new_content, fromfile=fromfile, tofile=tofile, context=context)


def list_branches_and_worktrees(project_dir: str) -> Any:
    """List git branches and worktrees (core git worktree helper)."""
    from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager as _f

    return _f.list_branches_and_worktrees(project_dir)


def get_git_worktree_manager() -> type[GitWorktreeManager]:
    """Core GitWorktreeManager class (lazy, for feature/async detection)."""
    from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager as _f

    return _f


def get_ignore_dirs() -> list[str]:
    """Default git-ignore directory names (core defaults)."""
    from johnston.core.domain.defaults.git_excludes import DEFAULT_IGNORE_DIRS as _f

    return _f
