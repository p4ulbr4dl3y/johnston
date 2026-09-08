import os
import threading
import time  # noqa: F401
from contextlib import contextmanager
from typing import Generator, Optional

from johnston_core.domain.defaults.git_excludes import DEFAULT_EXCLUDES
from johnston_core.domain.ports.checkpoint import set_default_checkpoint_manager
from johnston_core.infrastructure.platform.paths import SHADOW_REPOS_DIR
from johnston_core.infrastructure.runtime.git_utils import is_git_repository, run_git
from johnston_core.infrastructure.storage.git_checkpoint_diff import GitCheckpointDiffMixin
from johnston_core.infrastructure.storage.git_checkpoint_ops import GitCheckpointOpsMixin
from johnston_core.infrastructure.storage.git_checkpoint_restore import GitCheckpointRestoreMixin
from johnston_core.infrastructure.storage.git_diff_parser import parse_numstat, split_git_diff  # noqa: F401
from johnston_core.infrastructure.storage.git_shadow_env import (
    base_shadow_env,
    ensure_shadow_exclude,
    get_shadow_dir,
    shadow_index_env,
)

__all__ = ["GitCheckpointManager", "SHADOW_REPOS_DIR"]


class GitCheckpointManager(GitCheckpointOpsMixin, GitCheckpointRestoreMixin, GitCheckpointDiffMixin):
    """Manages isolated shadow Git checkpoints for chat sessions using custom refs and external shadow repos.

    Checkpoints capture the exact workspace state (tracked + untracked files)
    before each user message in a separate shadow Git repository located in ~/.johnston/shadow_repos/
    without altering current project directory or git state.
    """

    REF_PREFIX = "refs/johnston/checkpoints"
    ARCHIVE_PREFIX = "refs/johnston/archive"
    EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    DEFAULT_EXCLUDES = DEFAULT_EXCLUDES

    # Purged checkpoints are renamed into ARCHIVE_PREFIX and kept for this long
    # before their refs are dropped, so a mistaken rewind stays recoverable.
    ARCHIVE_TTL_DAYS = 7
    # Loose-object prune runs at most once per interval per shadow repo (throttle marker).
    PRUNE_INTERVAL_SECONDS = 24 * 3600
    # A shadow-repo index.lock older than this is stale (crashed process); younger
    # ones may belong to a concurrently running Johnston process and are left alone.
    STALE_LOCK_SECONDS = 30.0

    # Serializes workspace/shadow-repo mutations (create/restore/purge) per project/session
    # so a rewind restore cannot interleave with a concurrent checkpoint snapshot of
    # the same worktree. Run-git calls happen in worker threads (asyncio.to_thread).
    _LOCKS_GUARD = threading.Lock()
    _LOCKS: dict[str, threading.RLock] = {}

    @classmethod
    def _run_git(cls, *args, **kwargs):
        """Dispatches git execution through module-level run_git."""
        return run_git(*args, **kwargs)

    @classmethod
    def _get_lock(cls, key: str) -> threading.RLock:
        with cls._LOCKS_GUARD:
            lock = cls._LOCKS.get(key)
            if lock is None:
                lock = threading.RLock()
                cls._LOCKS[key] = lock
            return lock

    @classmethod
    def _ensure_shadow_exclude(cls, shadow_dir: str) -> None:
        ensure_shadow_exclude(shadow_dir, cls.DEFAULT_EXCLUDES, cls.STALE_LOCK_SECONDS)

    _base_shadow_env_cache: dict[tuple[str, str], dict] = {}

    @classmethod
    def _base_shadow_env(cls, shadow_dir: str, cwd: str) -> dict:
        return base_shadow_env(shadow_dir, cwd, cls._base_shadow_env_cache)

    @classmethod
    @contextmanager
    def _shadow_index_env(cls, shadow_dir: str, cwd: str) -> Generator[dict, None, None]:
        with shadow_index_env(shadow_dir, cwd, cls._base_shadow_env) as env:
            yield env

    @classmethod
    def _get_shadow_dir(cls, project_path: Optional[str] = None) -> tuple[str, str]:
        return get_shadow_dir(project_path)

    _initialized_repos: set[str] = set()

    @classmethod
    def is_git_repo(cls, project_path: Optional[str] = None) -> bool:
        shadow_dir, _ = cls._get_shadow_dir(project_path)
        if not os.path.exists(shadow_dir):
            cls._initialized_repos.discard(shadow_dir)
            return False
        if shadow_dir in cls._initialized_repos:
            return True
        res = cls._run_git(["rev-parse", "--git-dir"], cwd=shadow_dir)
        if res.returncode == 0:
            cls._initialized_repos.add(shadow_dir)
            return True
        return False

    @classmethod
    def get_ref_name(cls, session_id: str, message_index: int) -> str:
        return f"{cls.REF_PREFIX}/{session_id}/{message_index}"

    @classmethod
    def ensure_git_repo(cls, project_path: Optional[str] = None) -> bool:
        """Ensures an isolated shadow Git repository exists in ~/.johnston/shadow_repos for the project path."""
        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        if shadow_dir in cls._initialized_repos and os.path.exists(shadow_dir):
            return True

        os.makedirs(shadow_dir, exist_ok=True)

        rev_res = cls._run_git(["rev-parse", "--git-dir"], cwd=shadow_dir)
        newly_initialized = False
        if rev_res.returncode != 0:
            init_res = cls._run_git(["init", "--bare"], cwd=shadow_dir)
            if init_res.returncode != 0:
                return False
            newly_initialized = True

        if newly_initialized:
            cls._run_git(["config", "user.name", "Johnston AI"], cwd=shadow_dir)
            cls._run_git(["config", "user.email", "johnston@local"], cwd=shadow_dir)

        cls._ensure_shadow_exclude(shadow_dir)

        head_res = cls._run_git(["rev-parse", "--verify", "HEAD"], cwd=shadow_dir)
        if head_res.returncode != 0:
            # Single source of truth for the empty tree: prefer a live git
            # mktree (no stdin content) and fall back to the well-known constant.
            mktree_res = cls._run_git(["mktree"], cwd=shadow_dir)
            empty_tree_sha = mktree_res.stdout.strip() if mktree_res.returncode == 0 else cls.EMPTY_TREE_SHA
            commit_res = cls._run_git(
                ["commit-tree", empty_tree_sha, "-m", "Initial commit by Johnston"],
                cwd=shadow_dir,
            )
            if commit_res.returncode != 0:
                return False
            commit_sha = commit_res.stdout.strip()
            cls._run_git(["update-ref", "refs/heads/main", commit_sha], cwd=shadow_dir)
            cls._run_git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=shadow_dir)

        cls._initialized_repos.add(shadow_dir)
        return True

    @classmethod
    def is_valid_checkpoint_target(cls, project_path: Optional[str] = None) -> bool:
        """Checks if target path is a valid git workspace and NOT home or system root directory."""
        cwd = os.path.realpath(os.path.abspath(project_path or os.getcwd()))
        home = os.path.realpath(os.path.expanduser("~"))

        # Keep the home/root block first (cheap, avoids shelling out to git
        # for paths that should never be checkpoint targets), then delegate the
        # actual git-work-tree check to the shared helper.
        if cwd == home or os.path.dirname(cwd) == cwd:
            return False

        return is_git_repository(cwd)


set_default_checkpoint_manager(GitCheckpointManager)
