import os
import shutil
import time
from typing import Optional

__all__ = ["GitCheckpointRestoreMixin"]


class GitCheckpointRestoreMixin:
    """Restore and purge/archive mixin for GitCheckpointManager."""

    REF_PREFIX: str
    ARCHIVE_PREFIX: str
    ARCHIVE_TTL_DAYS: int
    PRUNE_INTERVAL_SECONDS: int

    @classmethod
    def _run_git(cls, *args, **kwargs):
        from johnston_core.infrastructure.runtime.git_utils import run_git

        return run_git(*args, **kwargs)

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
            rev_res = cls._run_git(["rev-parse", "--verify", ref_name], cwd=shadow_dir)
            if rev_res.returncode != 0:
                return False
            commit_sha = rev_res.stdout.strip()

            cat_res = cls._run_git(["cat-file", "-p", commit_sha], cwd=shadow_dir)
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
                    ls_res = cls._run_git(
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
                        res_co = cls._run_git(
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
                                    shutil.rmtree(abs_p, ignore_errors=True)
                                else:
                                    os.remove(abs_p)
                            except Exception:
                                pass

                    with cls._shadow_index_env(shadow_dir, cwd) as tmp_env:
                        cls._run_git(["add", "-A"], cwd=cwd, env=tmp_env, timeout=30.0)
                    return True
                except Exception:
                    return False

            try:
                res1 = cls._run_git(["read-tree", "--reset", "-u", commit_sha], cwd=cwd, env=env, timeout=60.0)
                if res1.returncode != 0:
                    return False

                cls._run_git(["clean", "-fd"], cwd=cwd, env=env, timeout=60.0)
                cls._run_git(["update-ref", "HEAD", parent_sha], cwd=shadow_dir, timeout=10.0)
                cls._run_git(["reset"], cwd=cwd, env=env, timeout=60.0)
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

            refs_res = cls._run_git(
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
                        cls._run_git(["update-ref", f"{archive_prefix}{idx}", sha], cwd=shadow_dir, timeout=5.0)
                    cls._run_git(["update-ref", "-d", ref], cwd=shadow_dir, timeout=5.0)

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
        refs_res = cls._run_git(
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
                            cls._run_git(["update-ref", "-d", ref], cwd=shadow_dir, timeout=2.0)
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

        cls._run_git(["prune", "--expire=now"], cwd=shadow_dir, timeout=30.0)
        try:
            with open(prune_stamp, "w") as f:
                f.write(str(int(now)))
        except OSError:
            pass
