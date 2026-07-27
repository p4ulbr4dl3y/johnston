import os
import shutil
import subprocess
from typing import List, Optional


class GitCheckpointManager:
    """Manages isolated shadow Git checkpoints for chat sessions using custom refs.

    Checkpoints capture the exact workspace state (tracked + untracked files)
    before each user message without altering current branch git log or status.
    """

    REF_PREFIX = "refs/johnston/checkpoints"

    @staticmethod
    def _run_git(args: List[str], cwd: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
        )

    @classmethod
    def is_git_repo(cls, project_path: Optional[str] = None) -> bool:
        cwd = os.path.realpath(os.path.abspath(project_path or os.getcwd()))
        res = cls._run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
        return res.returncode == 0 and res.stdout.strip() == "true"

    @classmethod
    def get_ref_name(cls, session_id: str, message_index: int) -> str:
        return f"{cls.REF_PREFIX}/{session_id}/{message_index}"

    @classmethod
    def ensure_git_repo(cls, project_path: Optional[str] = None) -> bool:
        """Ensures working directory is a git repository with at least one HEAD commit."""
        cwd = os.path.realpath(os.path.abspath(project_path or os.getcwd()))
        if not cls.is_git_repo(cwd):
            init_res = cls._run_git(["init"], cwd=cwd)
            if init_res.returncode != 0:
                return False
            cls._run_git(["config", "user.name", "Johnston AI"], cwd=cwd)
            cls._run_git(["config", "user.email", "johnston@local"], cwd=cwd)

        head_res = cls._run_git(["rev-parse", "HEAD"], cwd=cwd)
        if head_res.returncode != 0:
            cls._run_git(["config", "user.name", "Johnston AI"], cwd=cwd)
            cls._run_git(["config", "user.email", "johnston@local"], cwd=cwd)
            commit_res = cls._run_git(["commit", "--allow-empty", "-m", "Initial commit by Johnston"], cwd=cwd)
            return commit_res.returncode == 0
        return True

    @classmethod
    def create_checkpoint(
        cls,
        session_id: str,
        message_index: int,
        project_path: Optional[str] = None,
        auto_init: bool = True,
    ) -> Optional[str]:
        """Creates a shadow git commit containing tracked & untracked working tree state

        Saves commit SHA in refs/johnston/checkpoints/<session_id>/<message_index>.
        Returns commit SHA if created, None if not in a git repo.
        """
        cwd = os.path.realpath(os.path.abspath(project_path or os.getcwd()))
        if auto_init:
            if not cls.ensure_git_repo(cwd):
                return None
        else:
            if not cls.is_git_repo(cwd):
                return None

        ref_name = cls.get_ref_name(session_id, message_index)

        # Check HEAD SHA
        head_res = cls._run_git(["rev-parse", "HEAD"], cwd=cwd)
        if head_res.returncode != 0:
            return None
        head_sha = head_res.stdout.strip()

        # Create shadow index file to include all working tree changes (tracked + untracked)
        git_dir_res = cls._run_git(["rev-parse", "--git-dir"], cwd=cwd)
        if git_dir_res.returncode != 0:
            return None
        git_dir = os.path.abspath(os.path.join(cwd, git_dir_res.stdout.strip()))

        tmp_index = os.path.join(git_dir, f"johnston_tmp_index_{os.getpid()}")
        orig_index = os.path.join(git_dir, "index")

        if os.path.exists(orig_index):
            try:
                shutil.copy(orig_index, tmp_index)
            except Exception:
                pass

        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = tmp_index

        try:
            # Stage all untracked & tracked changes into temporary index
            cls._run_git(["add", "-A"], cwd=cwd, env=env)
            tree_res = cls._run_git(["write-tree"], cwd=cwd, env=env)
            if tree_res.returncode != 0:
                return None
            tree_sha = tree_res.stdout.strip()

            commit_res = cls._run_git(
                ["commit-tree", tree_sha, "-p", head_sha, "-m", f"Johnston Checkpoint {session_id}:{message_index}"],
                cwd=cwd,
                env=env,
            )
            if commit_res.returncode != 0:
                return None
            commit_sha = commit_res.stdout.strip()

            # Store in custom ref
            ref_res = cls._run_git(["update-ref", ref_name, commit_sha], cwd=cwd)
            if ref_res.returncode == 0:
                return commit_sha
            return None
        finally:
            if os.path.exists(tmp_index):
                try:
                    os.remove(tmp_index)
                except Exception:
                    pass

    @classmethod
    def restore_checkpoint(
        cls,
        session_id: str,
        message_index: int,
        project_path: Optional[str] = None,
    ) -> bool:
        """Restores repository working tree and HEAD state to saved checkpoint."""
        cwd = os.path.realpath(os.path.abspath(project_path or os.getcwd()))
        if not cls.is_git_repo(cwd):
            return False

        ref_name = cls.get_ref_name(session_id, message_index)
        rev_res = cls._run_git(["rev-parse", "--verify", ref_name], cwd=cwd)
        if rev_res.returncode != 0:
            return False
        commit_sha = rev_res.stdout.strip()

        # Parse commit object to get base parent commit (HEAD at checkpoint time)
        cat_res = cls._run_git(["cat-file", "-p", commit_sha], cwd=cwd)
        if cat_res.returncode != 0:
            return False

        parent_sha = commit_sha
        for line in cat_res.stdout.splitlines():
            if line.startswith("parent "):
                parent_sha = line.split()[1]
                break

        try:
            # 1. Reset HEAD to parent commit SHA
            cls._run_git(["reset", "--hard", parent_sha], cwd=cwd)
            # 2. Remove any untracked files created after checkpoint
            cls._run_git(["clean", "-fd"], cwd=cwd)
            # 3. Read tree from checkpoint commit into working directory
            cls._run_git(["read-tree", "--reset", "-u", commit_sha], cwd=cwd)
            # 4. Unstage changes so working tree mirrors exact index/untracked state
            cls._run_git(["reset"], cwd=cwd)
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
        """Deletes checkpoints with index > target_message_index for given session."""
        cwd = os.path.realpath(os.path.abspath(project_path or os.getcwd()))
        if not cls.is_git_repo(cwd):
            return

        refs_res = cls._run_git(["for-each-ref", "--format=%(refname)", f"{cls.REF_PREFIX}/{session_id}/*"], cwd=cwd)
        if refs_res.returncode != 0 or not refs_res.stdout.strip():
            return

        for ref in refs_res.stdout.splitlines():
            ref = ref.strip()
            if not ref:
                continue
            try:
                idx_str = ref.rstrip("/").split("/")[-1]
                idx = int(idx_str)
                if idx > target_message_index:
                    cls._run_git(["update-ref", "-d", ref], cwd=cwd)
            except ValueError:
                pass

    @classmethod
    def get_diff_stats(
        cls,
        session_id: str,
        message_index: int,
        project_path: Optional[str] = None,
    ) -> Optional[str]:
        """Calculates line changes (+additions / -deletions) between target checkpoint and current workspace.

        Returns string formatted like '+12 / -4', 'no changes', or None if checkpoint doesn't exist.
        """
        cwd = os.path.realpath(os.path.abspath(project_path or os.getcwd()))
        if not cls.is_git_repo(cwd):
            return None

        ref_name = cls.get_ref_name(session_id, message_index)
        rev_res = cls._run_git(["rev-parse", "--verify", ref_name], cwd=cwd)
        if rev_res.returncode != 0:
            return None
        commit_sha = rev_res.stdout.strip()

        git_dir_res = cls._run_git(["rev-parse", "--git-dir"], cwd=cwd)
        if git_dir_res.returncode != 0:
            return None
        git_dir = os.path.abspath(os.path.join(cwd, git_dir_res.stdout.strip()))

        tmp_index = os.path.join(git_dir, f"johnston_diff_tmp_index_{os.getpid()}")
        orig_index = os.path.join(git_dir, "index")

        if os.path.exists(orig_index):
            try:
                shutil.copy(orig_index, tmp_index)
            except Exception:
                pass

        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = tmp_index

        try:
            cls._run_git(["add", "-A"], cwd=cwd, env=env)
            diff_res = cls._run_git(["diff", "--cached", "--numstat", commit_sha], cwd=cwd, env=env)
            if diff_res.returncode != 0:
                return None

            added, deleted = 0, 0
            for line in diff_res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
                    added += int(parts[0])
                    deleted += int(parts[1])

            if added == 0 and deleted == 0:
                return "no changes"
            return f"+{added} / -{deleted}"
        except Exception:
            return None
        finally:
            if os.path.exists(tmp_index):
                try:
                    os.remove(tmp_index)
                except Exception:
                    pass

    @classmethod
    def delete_session_checkpoints(
        cls,
        session_id: str,
        project_path: Optional[str] = None,
    ) -> None:
        """Deletes all checkpoints for given session."""
        cls.purge_checkpoints_after(session_id, -1, project_path=project_path)
