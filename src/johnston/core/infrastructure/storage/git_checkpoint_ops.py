from typing import Optional

__all__ = ["GitCheckpointOpsMixin"]


class GitCheckpointOpsMixin:
    """Snapshot creation, staging, and turn finalization mixin for GitCheckpointManager."""

    REF_PREFIX: str

    @classmethod
    def _run_git(cls, *args, **kwargs):
        from johnston.core.infrastructure.runtime.git_utils import run_git

        return run_git(*args, **kwargs)

    @classmethod
    def _resolve_previous_checkpoint(
        cls,
        shadow_dir: str,
        session_id: str,
        message_index: int,
    ) -> Optional[str]:
        """Returns the commit sha of the nearest prior checkpoint (< message_index) of the session, or None."""
        refs_res = cls._run_git(
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
        read_res = cls._run_git(["read-tree", prev_sha], cwd=cwd, env=env, timeout=60.0)
        if read_res.returncode != 0:
            return None

        # Single pass: modified + deleted (worktree vs seeded index) + new
        # untracked non-ignored files — exactly the set to stage.
        delta_res = cls._run_git(
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
            tree_res = cls._run_git(["rev-parse", f"{prev_sha}^{{tree}}"], cwd=shadow_dir, timeout=5.0)
            if tree_res.returncode != 0:
                return None
            return tree_res.stdout.strip()

        # Stage only the delta paths on top of the seeded index. Pathspecs via
        # stdin (NUL-separated) handle spaces/quotes and large change sets;
        # literal-pathspecs keep glob metacharacters in real filenames
        # (e.g. "f[1].txt") from being expanded.
        add_res = cls._run_git(
            ["--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul"],
            cwd=cwd,
            env=env,
            input="\0".join(sorted(paths)),
            timeout=60.0,
        )
        if add_res.returncode != 0:
            return None

        tree_res = cls._run_git(["write-tree"], cwd=cwd, env=env)
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

            head_res = cls._run_git(["rev-parse", "--verify", "HEAD"], cwd=shadow_dir)
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
                    add_res = cls._run_git(["add", "-A"], cwd=cwd, env=env, timeout=60.0)
                    if add_res.returncode != 0:
                        return None
                    tree_res = cls._run_git(["write-tree"], cwd=cwd, env=env)
                    if tree_res.returncode != 0:
                        return None
                    tree_sha = tree_res.stdout.strip()

                commit_res = cls._run_git(
                    ["commit-tree", tree_sha, "-p", parent_sha, "-m", f"Johnston Checkpoint {session_id}:{message_index}"],
                    cwd=shadow_dir,
                    env=env,
                )
                if commit_res.returncode != 0:
                    return None
                commit_sha = commit_res.stdout.strip()

                ref_res = cls._run_git(["update-ref", ref_name, commit_sha], cwd=shadow_dir)
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
            rev_res = cls._run_git(["rev-parse", "--verify", ref_name], cwd=shadow_dir, timeout=2.0)
            if rev_res.returncode != 0:
                return []
            commit_sha = rev_res.stdout.strip()

            with cls._shadow_index_env(shadow_dir, cwd) as env:
                add_res = cls._run_git(["add", "-A"], cwd=cwd, env=env, timeout=30.0)
                if add_res.returncode != 0:
                    return []

                diff_res = cls._run_git(
                    ["-c", "core.quotepath=off", "diff", "--cached", "--name-only", commit_sha],
                    cwd=cwd,
                    env=env,
                    timeout=5.0,
                )
                if diff_res.returncode != 0:
                    return []

                return [f.strip() for f in diff_res.stdout.splitlines() if f.strip()]
