from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from johnston_core.infrastructure.storage.git_diff_parser import parse_numstat, split_git_diff

__all__ = ["GitCheckpointDiffMixin"]


class GitCheckpointDiffMixin:
    """Diff and numstat computation mixin for GitCheckpointManager."""

    REF_PREFIX: str
    ARCHIVE_PREFIX: str

    @classmethod
    def _run_git(cls, *args, **kwargs):
        from johnston_core.infrastructure.runtime.git_utils import run_git

        return run_git(*args, **kwargs)

    @staticmethod
    def _parse_numstat(output: str) -> tuple[int, int, list[str]]:
        return parse_numstat(output)

    @classmethod
    def _split_git_diff(cls, diff_output: str) -> list[tuple[str, str, int, int]]:
        return split_git_diff(diff_output)

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
                add_res = cls._run_git(["add", "-A"], cwd=cwd, env=env)
                if add_res.returncode != 0:
                    return results

                refs_res = cls._run_git(
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
                        rev_res = cls._run_git(["rev-parse", "--verify", ref_name], cwd=shadow_dir, timeout=1.0)
                        if rev_res.returncode != 0:
                            return msg_idx, None
                        commit_sha = rev_res.stdout.strip()

                    cmd = ["-c", "core.quotepath=off", "diff", "--cached", "--numstat", commit_sha]
                    if paths is not None:
                        cmd.extend(["--", *paths])

                    diff_res = cls._run_git(
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
                rev_res = cls._run_git(["rev-parse", "--verify", ref_name], cwd=shadow_dir, timeout=2.0)
                if rev_res.returncode == 0:
                    target_commit = rev_res.stdout.strip()
            else:
                refs_res = cls._run_git(
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
                        rev_res = cls._run_git(["rev-parse", "--verify", earliest_ref], cwd=shadow_dir, timeout=2.0)
                        if rev_res.returncode == 0:
                            target_commit = rev_res.stdout.strip()

            if not target_commit:
                return []

            with cls._shadow_index_env(shadow_dir, cwd) as env:
                add_res = cls._run_git(["add", "-A"], cwd=cwd, env=env, timeout=10.0)
                if add_res.returncode != 0:
                    return []

                cmd = ["-c", "core.quotepath=off", "diff", "--cached", target_commit]
                if scoped_files is not None:
                    cmd.extend(["--", *scoped_files])

                diff_res = cls._run_git(
                    cmd,
                    cwd=cwd,
                    env=env,
                    timeout=10.0,
                )
                if diff_res.returncode != 0 or not diff_res.stdout.strip():
                    return []

                return cls._split_git_diff(diff_res.stdout)
