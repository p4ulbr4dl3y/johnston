import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Generator, Optional

from core.domain.defaults.git_excludes import DEFAULT_EXCLUDES
from core.domain.ports.checkpoint import set_default_checkpoint_manager
from core.infrastructure.platform.paths import SHADOW_REPOS_DIR
from core.infrastructure.runtime.git_utils import is_git_repository, run_git
from core.infrastructure.storage.git_diff_parser import parse_numstat, split_git_diff
from core.infrastructure.storage.git_shadow_env import (
    base_shadow_env,
    ensure_shadow_exclude,
    get_shadow_dir,
    shadow_index_env,
)

__all__ = ["GitCheckpointManager", "SHADOW_REPOS_DIR"]


class GitCheckpointManager:
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

    @staticmethod
    def _parse_numstat(output: str) -> tuple[int, int, list[str]]:
        return parse_numstat(output)

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
        res = run_git(["rev-parse", "--git-dir"], cwd=shadow_dir)
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

        rev_res = run_git(["rev-parse", "--git-dir"], cwd=shadow_dir)
        newly_initialized = False
        if rev_res.returncode != 0:
            init_res = run_git(["init", "--bare"], cwd=shadow_dir)
            if init_res.returncode != 0:
                return False
            newly_initialized = True

        if newly_initialized:
            run_git(["config", "user.name", "Johnston AI"], cwd=shadow_dir)
            run_git(["config", "user.email", "johnston@local"], cwd=shadow_dir)

        cls._ensure_shadow_exclude(shadow_dir)

        head_res = run_git(["rev-parse", "--verify", "HEAD"], cwd=shadow_dir)
        if head_res.returncode != 0:
            # Single source of truth for the empty tree: prefer a live git
            # mktree (no stdin content) and fall back to the well-known constant.
            mktree_res = run_git(["mktree"], cwd=shadow_dir)
            empty_tree_sha = mktree_res.stdout.strip() if mktree_res.returncode == 0 else cls.EMPTY_TREE_SHA
            commit_res = run_git(
                ["commit-tree", empty_tree_sha, "-m", "Initial commit by Johnston"],
                cwd=shadow_dir,
            )
            if commit_res.returncode != 0:
                return False
            commit_sha = commit_res.stdout.strip()
            run_git(["update-ref", "refs/heads/main", commit_sha], cwd=shadow_dir)
            run_git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=shadow_dir)

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

    @classmethod
    def _resolve_previous_checkpoint(
        cls,
        shadow_dir: str,
        session_id: str,
        message_index: int,
    ) -> Optional[str]:
        """Returns the commit sha of the nearest prior checkpoint (< message_index) of the session, or None."""
        refs_res = run_git(
            ["for-each-ref", "--format=%(objectname) %(refname)", f"{cls.REF_PREFIX}/{session_id}/"],
            cwd=shadow_dir,
            timeout=5.0,
        )
        if refs_res.returncode != 0:
            return None

        sid_prefix = f"{cls.REF_PREFIX}/{session_id}/"
        best_idx = -1
        best_sha: Optional[str] = None
        for line in refs_res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            sha, ref = parts[0], parts[1]
            try:
                idx = int(ref[len(sid_prefix):].rstrip("/"))
            except ValueError:
                continue
            if best_idx < idx < message_index:
                best_idx = idx
                best_sha = sha
        return best_sha

    @classmethod
    def _stage_delta_index(
        cls,
        shadow_dir: str,
        cwd: str,
        prev_sha: str,
        env: dict,
    ) -> Optional[str]:
        """Stages only the paths that changed since ``prev_sha`` into the (temp) shadow index.

        Returns the tree sha of the current workspace state, or None if the delta
        staging could not be completed (the caller then falls back to a full
        ``add -A`` snapshot). A delta index that missed any change would produce
        a wrong tree, so every step must succeed before a tree is returned.
        """
        # Seed the tmp index from the previous checkpoint's tree so change
        # detection sees the checkpoint's tracked set — an empty index would
        # report every workspace file as new/untracked.
        read_res = run_git(["read-tree", prev_sha], cwd=cwd, env=env, timeout=60.0)
        if read_res.returncode != 0:
            return None

        # Single pass: modified + deleted (worktree vs seeded index) + new
        # untracked non-ignored files — exactly the set to stage.
        delta_res = run_git(
            ["ls-files", "--modified", "--deleted", "--others", "--exclude-standard", "-z"],
            cwd=cwd,
            env=env,
            timeout=60.0,
        )
        if delta_res.returncode != 0:
            return None

        paths = {p for p in delta_res.stdout.split("\0") if p}
        if not paths:
            # Workspace matches the previous checkpoint exactly: reuse its tree
            # instead of building a new one from an empty index.
            tree_res = run_git(["rev-parse", f"{prev_sha}^{{tree}}"], cwd=shadow_dir, timeout=5.0)
            if tree_res.returncode != 0:
                return None
            return tree_res.stdout.strip()

        # Stage only the delta paths on top of the seeded index. Pathspecs via
        # stdin (NUL-separated) handle spaces/quotes and large change sets;
        # literal-pathspecs keep glob metacharacters in real filenames
        # (e.g. "f[1].txt") from being expanded.
        add_res = run_git(
            ["--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul"],
            cwd=cwd,
            env=env,
            input="\0".join(sorted(paths)),
            timeout=60.0,
        )
        if add_res.returncode != 0:
            return None

        tree_res = run_git(["write-tree"], cwd=cwd, env=env)
        if tree_res.returncode != 0:
            return None
        return tree_res.stdout.strip()

    @classmethod
    def create_checkpoint(
        cls,
        session_id: str,
        message_index: int,
        project_path: Optional[str] = None,
        auto_init: bool = True,
    ) -> Optional[str]:
        """Creates a shadow git commit containing tracked & untracked working tree state.

        Saves commit SHA in refs/johnston/checkpoints/<session_id>/<message_index> inside shadow repo.
        Returns commit SHA if created, None if not initialized and auto_init=False.
        """
        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        with cls._get_lock(cwd):
            if not cls.is_valid_checkpoint_target(project_path):
                return None

            if auto_init:
                if not cls.ensure_git_repo(cwd):
                    return None
            else:
                if not cls.is_git_repo(cwd):
                    return None

            ref_name = cls.get_ref_name(session_id, message_index)

            head_res = run_git(["rev-parse", "--verify", "HEAD"], cwd=shadow_dir)
            if head_res.returncode != 0:
                return None
            head_sha = head_res.stdout.strip()

            with cls._shadow_index_env(shadow_dir, cwd) as env:
                # Incremental snapshot: when a prior checkpoint of the session
                # exists, base the new one on it and stage only the paths that
                # changed since (edits/new/deleted) — no full-tree `add -A`
                # re-hash. The commit's parent becomes that prior checkpoint;
                # without one, the parent is the shadow HEAD (unchanged legacy
                # behavior) and a full `add -A` snapshot is taken.
                #
                # A failed/partial staging must never produce a checkpoint: the
                # tree would silently miss files and a later restore would
                # delete them from the workspace. Any delta-step failure falls
                # back to the full snapshot, which is always safe and matches
                # the previous behavior.
                parent_sha = head_sha
                tree_sha: Optional[str] = None
                prev_sha = cls._resolve_previous_checkpoint(shadow_dir, session_id, message_index)
                if prev_sha is not None:
                    tree_sha = cls._stage_delta_index(shadow_dir, cwd, prev_sha, env)
                    if tree_sha is not None:
                        parent_sha = prev_sha

                if tree_sha is None:
                    add_res = run_git(["add", "-A"], cwd=cwd, env=env, timeout=60.0)
                    if add_res.returncode != 0:
                        return None
                    tree_res = run_git(["write-tree"], cwd=cwd, env=env)
                    if tree_res.returncode != 0:
                        return None
                    tree_sha = tree_res.stdout.strip()

                commit_res = run_git(
                    ["commit-tree", tree_sha, "-p", parent_sha, "-m", f"Johnston Checkpoint {session_id}:{message_index}"],
                    cwd=shadow_dir,
                    env=env,
                )
                if commit_res.returncode != 0:
                    return None
                commit_sha = commit_res.stdout.strip()

                ref_res = run_git(["update-ref", ref_name, commit_sha], cwd=shadow_dir)
                if ref_res.returncode == 0:
                    return commit_sha
                return None

    @classmethod
    def finalize_turn(
        cls,
        session_id: str,
        message_index: int,
        project_path: Optional[str] = None,
    ) -> list[str]:
        """Captures files modified during the turn compared to the start checkpoint."""
        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        with cls._get_lock(cwd):
            if not cls.is_git_repo(cwd):
                return []

            cls._ensure_shadow_exclude(shadow_dir)
            ref_name = cls.get_ref_name(session_id, message_index)
            rev_res = run_git(["rev-parse", "--verify", ref_name], cwd=shadow_dir, timeout=2.0)
            if rev_res.returncode != 0:
                return []
            commit_sha = rev_res.stdout.strip()

            with cls._shadow_index_env(shadow_dir, cwd) as env:
                add_res = run_git(["add", "-A"], cwd=cwd, env=env, timeout=30.0)
                if add_res.returncode != 0:
                    return []

                diff_res = run_git(
                    ["-c", "core.quotepath=off", "diff", "--cached", "--name-only", commit_sha],
                    cwd=cwd,
                    env=env,
                    timeout=5.0,
                )
                if diff_res.returncode != 0:
                    return []

                return [f.strip() for f in diff_res.stdout.splitlines() if f.strip()]

    @classmethod
    def restore_checkpoint(
        cls,
        session_id: str,
        message_index: int,
        project_path: Optional[str] = None,
        files_to_restore: Optional[list[str]] = None,
    ) -> bool:
        """Restores repository working tree state to saved checkpoint."""
        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        with cls._get_lock(cwd):
            if not cls.is_git_repo(cwd):
                return False

            ref_name = cls.get_ref_name(session_id, message_index)
            rev_res = run_git(["rev-parse", "--verify", ref_name], cwd=shadow_dir)
            if rev_res.returncode != 0:
                return False
            commit_sha = rev_res.stdout.strip()

            cat_res = run_git(["cat-file", "-p", commit_sha], cwd=shadow_dir)
            if cat_res.returncode != 0:
                return False

            parent_sha = commit_sha
            for line in cat_res.stdout.splitlines():
                if line.startswith("parent "):
                    parent_sha = line.split()[1]
                    break

            env = cls._base_shadow_env(shadow_dir, cwd)

            if files_to_restore is not None:
                if not files_to_restore:
                    return True
                try:
                    existing_in_cp = set()
                    ls_res = run_git(
                        ["-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", commit_sha, "--", *files_to_restore],
                        cwd=cwd,
                        env=env,
                        timeout=10.0,
                    )
                    if ls_res.returncode == 0:
                        for f in ls_res.stdout.splitlines():
                            f = f.strip()
                            if f:
                                existing_in_cp.add(f)

                    to_checkout = [f for f in files_to_restore if f in existing_in_cp]
                    to_remove = [f for f in files_to_restore if f not in existing_in_cp]

                    if to_checkout:
                        res_co = run_git(
                            ["checkout", commit_sha, "--", *to_checkout],
                            cwd=cwd,
                            env=env,
                            timeout=30.0,
                        )
                        if res_co.returncode != 0:
                            return False

                    for f in to_remove:
                        abs_p = os.path.join(cwd, f)
                        if os.path.exists(abs_p) or os.path.islink(abs_p):
                            try:
                                if os.path.isdir(abs_p) and not os.path.islink(abs_p):
                                    import shutil
                                    shutil.rmtree(abs_p, ignore_errors=True)
                                else:
                                    os.remove(abs_p)
                            except Exception:
                                pass

                    with cls._shadow_index_env(shadow_dir, cwd) as tmp_env:
                        run_git(["add", "-A"], cwd=cwd, env=tmp_env, timeout=30.0)
                    return True
                except Exception:
                    return False

            try:
                res1 = run_git(["read-tree", "--reset", "-u", commit_sha], cwd=cwd, env=env, timeout=60.0)
                if res1.returncode != 0:
                    return False

                run_git(["clean", "-fd"], cwd=cwd, env=env, timeout=60.0)
                run_git(["update-ref", "HEAD", parent_sha], cwd=shadow_dir, timeout=10.0)
                run_git(["reset"], cwd=cwd, env=env, timeout=60.0)
                return True
            except Exception:
                return False

    @classmethod
    def purge_checkpoints_after(
        cls,
        session_id: str,
        target_message_index: int,
        project_path: Optional[str] = None,
    ) -> None:
        """Retires checkpoints with index > target_message_index for given session.

        Refs are renamed into the archive namespace (``ARCHIVE_PREFIX``) instead of
        being deleted, so a mistaken rewind stays recoverable for
        ``ARCHIVE_TTL_DAYS`` days. Expired archives are dropped opportunistically.
        """
        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        with cls._get_lock(cwd):
            if not cls.is_git_repo(cwd):
                return

            refs_res = run_git(
                ["for-each-ref", "--format=%(objectname) %(refname)", f"{cls.REF_PREFIX}/{session_id}/"],
                cwd=shadow_dir,
                timeout=5.0,
            )
            if refs_res.returncode != 0:
                return

            sid_prefix = f"{cls.REF_PREFIX}/{session_id}/"
            archive_prefix = f"{cls.ARCHIVE_PREFIX}/{session_id}/"
            # Individual update-ref calls (not `--stdin`) — git-for-Windows can
            # reject `update-ref --stdin` input with a parse error, which would
            # silently skip the ref moves and leave checkpoints restorable.
            for line in refs_res.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) != 2:
                    continue
                sha, ref = parts[0], parts[1]
                try:
                    idx_str = ref[len(sid_prefix):].rstrip("/")
                    idx = int(idx_str)
                except ValueError:
                    continue
                if idx > target_message_index:
                    if sha:
                        run_git(["update-ref", f"{archive_prefix}{idx}", sha], cwd=shadow_dir, timeout=5.0)
                    run_git(["update-ref", "-d", ref], cwd=shadow_dir, timeout=5.0)

            cls._prune_expired_archives(shadow_dir)

    @classmethod
    def _prune_expired_archives(cls, shadow_dir: str) -> None:
        """Drops archived checkpoint refs older than ``ARCHIVE_TTL_DAYS``.

        Age is measured by the checkpoint commit's committer date (a conservative
        proxy for archive age). Unreachable loose objects are pruned at most once
        per ``PRUNE_INTERVAL_SECONDS`` per shadow repo.
        """
        # 1. Drop stale archived refs.
        cutoff = time.time() - cls.ARCHIVE_TTL_DAYS * 86400.0
        refs_res = run_git(
            ["for-each-ref", "--format=%(refname) %(committerdate:raw)", cls.ARCHIVE_PREFIX],
            cwd=shadow_dir,
            timeout=5.0,
        )
        if refs_res.returncode == 0 and refs_res.stdout.strip():
            for line in refs_res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    ref = parts[0]
                    try:
                        commit_ts = float(parts[1])
                        if commit_ts < cutoff:
                            run_git(["update-ref", "-d", ref], cwd=shadow_dir, timeout=2.0)
                    except ValueError:
                        pass

        # 2. Prune loose objects, throttled to at most once per interval.
        prune_stamp = os.path.join(shadow_dir, ".last_prune")
        now = time.time()
        try:
            if os.path.exists(prune_stamp):
                last_prune = os.path.getmtime(prune_stamp)
                if now - last_prune < cls.PRUNE_INTERVAL_SECONDS:
                    return
        except OSError:
            pass

        run_git(["prune", "--expire=now"], cwd=shadow_dir, timeout=30.0)
        try:
            with open(prune_stamp, "w") as f:
                f.write(str(int(now)))
        except OSError:
            pass

    @classmethod
    def get_diff_details_batch(
        cls,
        session_id: str,
        message_indices: list[int],
        project_path: Optional[str] = None,
        scoped_files: Optional[dict[int, list[str]]] = None,
    ) -> dict[int, Optional[tuple[str, list[str]]]]:
        """Calculates line changes and changed files between checkpoints and current workspace.

        Stages current workspace ONCE to calculate all diff details efficiently.
        Returns dict mapping message_index -> (stat_string, changed_files_list) or None.
        """
        results: dict[int, Optional[tuple[str, list[str]]]] = {idx: None for idx in message_indices}
        if not message_indices:
            return results

        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        with cls._get_lock(cwd):
            if not cls.is_git_repo(cwd):
                return results

            cls._ensure_shadow_exclude(shadow_dir)

            with cls._shadow_index_env(shadow_dir, cwd) as env:
                add_res = run_git(["add", "-A"], cwd=cwd, env=env)
                if add_res.returncode != 0:
                    return results

                refs_res = run_git(
                    ["for-each-ref", "--format=%(objectname) %(refname)", f"{cls.REF_PREFIX}/{session_id}/"],
                    cwd=shadow_dir,
                    timeout=3.0,
                )
                ref_map: dict[str, str] = {}
                if refs_res.returncode == 0:
                    for line in refs_res.stdout.splitlines():
                        parts = line.strip().split(maxsplit=1)
                        if len(parts) == 2:
                            ref_map[parts[1]] = parts[0]

                def _fetch_diff_for_idx(msg_idx: int) -> tuple[int, Optional[tuple[str, list[str]]]]:
                    if scoped_files is not None:
                        paths = scoped_files.get(msg_idx)
                        if paths is not None and not paths:
                            return msg_idx, ("no changes", [])
                    else:
                        paths = None

                    ref_name = cls.get_ref_name(session_id, msg_idx)
                    commit_sha = ref_map.get(ref_name)
                    if not commit_sha:
                        rev_res = run_git(["rev-parse", "--verify", ref_name], cwd=shadow_dir, timeout=1.0)
                        if rev_res.returncode != 0:
                            return msg_idx, None
                        commit_sha = rev_res.stdout.strip()

                    cmd = ["-c", "core.quotepath=off", "diff", "--cached", "--numstat", commit_sha]
                    if paths is not None:
                        cmd.extend(["--", *paths])

                    diff_res = run_git(
                        cmd,
                        cwd=cwd,
                        env=env,
                        timeout=5.0,
                    )
                    if diff_res.returncode != 0:
                        return msg_idx, None

                    added, deleted, files = cls._parse_numstat(diff_res.stdout)

                    if added == 0 and deleted == 0:
                        return msg_idx, ("no changes", [])
                    else:
                        file_count = len(files)
                        plural = "files" if file_count != 1 else "file"
                        return msg_idx, (f"{file_count} {plural}, +{added} / -{deleted}", files)

                if len(message_indices) > 1:
                    max_w = min(12, len(message_indices))
                    with ThreadPoolExecutor(max_workers=max_w) as executor:
                        for msg_idx, res in executor.map(_fetch_diff_for_idx, message_indices):
                            if res is not None:
                                results[msg_idx] = res
                elif message_indices:
                    msg_idx, res = _fetch_diff_for_idx(message_indices[0])
                    if res is not None:
                        results[msg_idx] = res

            return results

    @classmethod
    def _split_git_diff(cls, diff_output: str) -> list[tuple[str, str, int, int]]:
        return split_git_diff(diff_output)

    @classmethod
    def get_checkpoint_diff(
        cls,
        session_id: str,
        message_index: Optional[int] = None,
        project_path: Optional[str] = None,
        scoped_files: Optional[list[str]] = None,
    ) -> list[tuple[str, str, int, int]]:
        """Calculates full diff between a session checkpoint and the current workspace.

        If message_index is None, finds the earliest available checkpoint for the session.
        Returns a list of tuples: (file_path, diff_text, added_lines, deleted_lines).
        """
        if scoped_files is not None and not scoped_files:
            return []

        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        with cls._get_lock(cwd):
            if not cls.is_git_repo(cwd):
                return []

            cls._ensure_shadow_exclude(shadow_dir)

            target_commit: Optional[str] = None
            if message_index is not None:
                ref_name = cls.get_ref_name(session_id, message_index)
                rev_res = run_git(["rev-parse", "--verify", ref_name], cwd=shadow_dir, timeout=2.0)
                if rev_res.returncode == 0:
                    target_commit = rev_res.stdout.strip()
            else:
                refs_res = run_git(
                    ["for-each-ref", "--format=%(refname)", f"{cls.REF_PREFIX}/{session_id}/*"],
                    cwd=shadow_dir,
                    timeout=2.0,
                )
                if refs_res.returncode == 0 and refs_res.stdout.strip():
                    valid_refs = []
                    for ref in refs_res.stdout.splitlines():
                        ref = ref.strip()
                        if not ref:
                            continue
                        try:
                            idx = int(ref.rstrip("/").split("/")[-1])
                            valid_refs.append((idx, ref))
                        except ValueError:
                            pass
                    if valid_refs:
                        valid_refs.sort(key=lambda x: x[0])
                        earliest_ref = valid_refs[0][1]
                        rev_res = run_git(["rev-parse", "--verify", earliest_ref], cwd=shadow_dir, timeout=2.0)
                        if rev_res.returncode == 0:
                            target_commit = rev_res.stdout.strip()

            if not target_commit:
                return []

            with cls._shadow_index_env(shadow_dir, cwd) as env:
                add_res = run_git(["add", "-A"], cwd=cwd, env=env, timeout=10.0)
                if add_res.returncode != 0:
                    return []

                cmd = ["-c", "core.quotepath=off", "diff", "--cached", target_commit]
                if scoped_files is not None:
                    cmd.extend(["--", *scoped_files])

                diff_res = run_git(
                    cmd,
                    cwd=cwd,
                    env=env,
                    timeout=10.0,
                )
                if diff_res.returncode != 0 or not diff_res.stdout.strip():
                    return []

                return cls._split_git_diff(diff_res.stdout)


set_default_checkpoint_manager(GitCheckpointManager)

