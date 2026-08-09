import hashlib
import os
import subprocess
import uuid
from contextlib import contextmanager
from typing import Generator, List, Optional

from core.git_utils import run_git
from core.platform_utils import johnston_config_dir


class GitCheckpointManager:
    """Manages isolated shadow Git checkpoints for chat sessions using custom refs and external shadow repos.

    Checkpoints capture the exact workspace state (tracked + untracked files)
    before each user message in a separate shadow Git repository located in ~/.johnston/shadow_repos/
    without altering current project directory or git state.
    """

    REF_PREFIX = "refs/johnston/checkpoints"
    EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    DEFAULT_EXCLUDES = (
        ".git/\n"
        ".johnston/\n"
        "venv/\n"
        ".venv/\n"
        "env/\n"
        ".env/\n"
        "ENV/\n"
        "__pycache__/\n"
        "*.pyc\n"
        "*.pyo\n"
        "*.pyd\n"
        ".pytest_cache/\n"
        ".mypy_cache/\n"
        ".ruff_cache/\n"
        ".coverage\n"
        "htmlcov/\n"
        "dist/\n"
        "build/\n"
        "eggs/\n"
        ".eggs/\n"
        "*.egg-info/\n"
        "node_modules/\n"
        ".next/\n"
        ".nuxt/\n"
        ".svelte-kit/\n"
        ".out/\n"
        ".cache/\n"
        "bower_components/\n"
        ".DS_Store\n"
        "*.log\n"
        "*.tmp\n"
        "*.temp\n"
        "tmp/\n"
        "temp/\n"
        ".tmp/\n"
        ".temp/\n"
        ".pixi/\n"
        ".conda/\n"
        "conda-env/\n"
        "envs/\n"
        ".envs/\n"
        "target/\n"
        "vendor/\n"
        ".pnpm-store/\n"
        ".yarn/\n"
        ".gradle/\n"
        ".m2/\n"
        ".ivy2/\n"
        ".hypothesis/\n"
        ".parcel-cache/\n"
        ".turbo/\n"
        ".astro/\n"
        "out/\n"
        "wandb/\n"
        ".wandb/\n"
        "mlruns/\n"
        "*.gguf\n"
        "*.bin\n"
        "*.safetensors\n"
        "*.pth\n"
        "*.pt\n"
        "*.onnx\n"
        "*.onnx_data\n"
        "*.tflite\n"
        "*.h5\n"
        "*.hdf5\n"
        "*.ckpt\n"
        "*.model\n"
        "*.weights\n"
        "*.pb\n"
        "*.ptl\n"
        "*.pkl\n"
        "*.pickle\n"
        "*.feather\n"
        "*.ort\n"
        "*.tensor\n"
        "*.tensors\n"
        "*.msgpack\n"
        "*.parquet\n"
        "*.arrow\n"
        "*.npz\n"
        "*.npy\n"
        "*.zip\n"
        "*.tar\n"
        "*.tar.gz\n"
        "*.tgz\n"
        "*.gz\n"
        "*.bz2\n"
        "*.xz\n"
        "*.zst\n"
        "*.lz4\n"
        "*.7z\n"
        "*.rar\n"
        "*.iso\n"
        "*.dmg\n"
        "*.pkg\n"
        "*.deb\n"
        "*.rpm\n"
        "*.so\n"
        "*.dylib\n"
        "*.dll\n"
        "*.exe\n"
        "*.a\n"
        "*.o\n"
        "*.obj\n"
        "*.class\n"
        "*.jar\n"
        "*.war\n"
        "*.ear\n"
        "*.wasm\n"
        "*.lib\n"
        "*.sqlite\n"
        "*.sqlite3\n"
        "*.db\n"
        "*.mdb\n"
        "*.ldb\n"
        "*.leveldb\n"
        "*.mp4\n"
        "*.mkv\n"
        "*.avi\n"
        "*.mov\n"
        "*.webm\n"
        "*.flv\n"
        "*.wmv\n"
        "*.m4v\n"
        "*.mp3\n"
        "*.wav\n"
        "*.flac\n"
        "*.aac\n"
        "*.ogg\n"
        "*.m4a\n"
        "*.psd\n"
        "*.ai\n"
        "*.tiff\n"
        "*.tif\n"
        "*.raw\n"
        "*.dmp\n"
        "*.dump\n"
        "*.stackdump\n"
        "core.*\n"
        "desktop.ini\n"
    )

    @classmethod
    def _ensure_shadow_exclude(cls, shadow_dir: str) -> None:
        info_dir = os.path.join(shadow_dir, "info")
        exclude_file = os.path.join(info_dir, "exclude")
        try:
            os.makedirs(info_dir, exist_ok=True)
            existing = ""
            if os.path.exists(exclude_file):
                with open(exclude_file, "r", encoding="utf-8") as f:
                    existing = f.read()

            lines = set(line.strip() for line in existing.splitlines() if line.strip())
            new_lines = []
            for pattern in cls.DEFAULT_EXCLUDES.strip().splitlines():
                if pattern not in lines:
                    new_lines.append(pattern)

            if new_lines:
                with open(exclude_file, "a", encoding="utf-8") as f:
                    if existing and not existing.endswith("\n"):
                        f.write("\n")
                    f.write("\n".join(new_lines) + "\n")
        except Exception:
            pass

    @staticmethod
    def _run_git(
        args: List[str],
        cwd: str,
        env: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> subprocess.CompletedProcess:
        return run_git(args=args, cwd=cwd, env=env, timeout=timeout)

    @classmethod
    @contextmanager
    def _shadow_index_env(cls, shadow_dir: str, cwd: str) -> Generator[dict, None, None]:
        tmp_index = os.path.join(shadow_dir, f"johnston_tmp_index_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        env = os.environ.copy()
        env["GIT_DIR"] = shadow_dir
        env["GIT_WORK_TREE"] = cwd
        env["GIT_INDEX_FILE"] = tmp_index
        try:
            yield env
        finally:
            if os.path.exists(tmp_index):
                try:
                    os.remove(tmp_index)
                except Exception:
                    pass

    @classmethod
    def _get_shadow_dir(cls, project_path: Optional[str] = None) -> tuple[str, str]:
        cwd = os.path.realpath(os.path.abspath(project_path or os.getcwd()))
        hash_id = hashlib.md5(cwd.encode("utf-8")).hexdigest()
        shadow_dir = os.path.join(str(johnston_config_dir()), "shadow_repos", f"{hash_id}.git")
        return shadow_dir, cwd

    @classmethod
    def is_git_repo(cls, project_path: Optional[str] = None) -> bool:
        shadow_dir, _ = cls._get_shadow_dir(project_path)
        if not os.path.exists(shadow_dir):
            return False
        res = cls._run_git(["rev-parse", "--git-dir"], cwd=shadow_dir)
        return res.returncode == 0

    @classmethod
    def get_ref_name(cls, session_id: str, message_index: int) -> str:
        return f"{cls.REF_PREFIX}/{session_id}/{message_index}"

    @classmethod
    def ensure_git_repo(cls, project_path: Optional[str] = None) -> bool:
        """Ensures an isolated shadow Git repository exists in ~/.johnston/shadow_repos for the project path."""
        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        os.makedirs(shadow_dir, exist_ok=True)

        rev_res = cls._run_git(["rev-parse", "--git-dir"], cwd=shadow_dir)
        if rev_res.returncode != 0:
            init_res = cls._run_git(["init", "--bare"], cwd=shadow_dir)
            if init_res.returncode != 0:
                return False

        cls._run_git(["config", "user.name", "Johnston AI"], cwd=shadow_dir)
        cls._run_git(["config", "user.email", "johnston@local"], cwd=shadow_dir)
        cls._ensure_shadow_exclude(shadow_dir)

        head_res = cls._run_git(["rev-parse", "--verify", "HEAD"], cwd=shadow_dir)
        if head_res.returncode != 0:
            mktree_res = subprocess.run(
                ["git", "mktree"],
                cwd=shadow_dir,
                input="",
                capture_output=True,
                text=True,
            )
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

        return True

    @classmethod
    def is_valid_checkpoint_target(cls, project_path: Optional[str] = None) -> bool:
        """Checks if target path is a valid git workspace and NOT home or system root directory."""
        cwd = os.path.realpath(os.path.abspath(project_path or os.getcwd()))
        home = os.path.realpath(os.path.expanduser("~"))

        # Block home dir and any drive/system root ('/', 'C:\', 'D:\', etc.)
        if cwd == home or os.path.dirname(cwd) == cwd:
            return False

        res = cls._run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
        return res.returncode == 0 and res.stdout.strip() == "true"

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
        if not cls.is_valid_checkpoint_target(project_path):
            return None

        shadow_dir, cwd = cls._get_shadow_dir(project_path)
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
            cls._run_git(["add", "-A"], cwd=cwd, env=env)
            tree_res = cls._run_git(["write-tree"], cwd=cwd, env=env)
            if tree_res.returncode != 0:
                return None
            tree_sha = tree_res.stdout.strip()

            commit_res = cls._run_git(
                ["commit-tree", tree_sha, "-p", head_sha, "-m", f"Johnston Checkpoint {session_id}:{message_index}"],
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
    def restore_checkpoint(
        cls,
        session_id: str,
        message_index: int,
        project_path: Optional[str] = None,
    ) -> bool:
        """Restores repository working tree state to saved checkpoint."""
        shadow_dir, cwd = cls._get_shadow_dir(project_path)
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

        env = os.environ.copy()
        env["GIT_DIR"] = shadow_dir
        env["GIT_WORK_TREE"] = cwd

        try:
            res1 = cls._run_git(["read-tree", "--reset", "-u", commit_sha], cwd=cwd, env=env)
            if res1.returncode != 0:
                return False

            cls._run_git(["clean", "-fd"], cwd=cwd, env=env)
            cls._run_git(["update-ref", "HEAD", parent_sha], cwd=shadow_dir)
            cls._run_git(["reset"], cwd=cwd, env=env)
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
        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        if not cls.is_git_repo(cwd):
            return

        refs_res = cls._run_git(["for-each-ref", "--format=%(refname)", f"{cls.REF_PREFIX}/{session_id}/*"], cwd=shadow_dir)
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
                    cls._run_git(["update-ref", "-d", ref], cwd=shadow_dir)
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
        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        if not cls.is_git_repo(cwd):
            return None

        ref_name = cls.get_ref_name(session_id, message_index)
        rev_res = cls._run_git(["rev-parse", "--verify", ref_name], cwd=shadow_dir)
        if rev_res.returncode != 0:
            return None
        commit_sha = rev_res.stdout.strip()

        with cls._shadow_index_env(shadow_dir, cwd) as env:
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

    @classmethod
    def get_diff_stats_batch(
        cls,
        session_id: str,
        message_indices: List[int],
        project_path: Optional[str] = None,
    ) -> dict[int, Optional[str]]:
        """Calculates line changes between each saved checkpoint in message_indices and current workspace.

        Stages current workspace ONCE to calculate all diff stats efficiently.
        Returns dict mapping message_index -> stat string (e.g. '+12 / -4', 'no changes', or None).
        """
        results: dict[int, Optional[str]] = {idx: None for idx in message_indices}
        if not message_indices:
            return results

        shadow_dir, cwd = cls._get_shadow_dir(project_path)
        if not cls.is_git_repo(cwd):
            return results

        cls._ensure_shadow_exclude(shadow_dir)

        with cls._shadow_index_env(shadow_dir, cwd) as env:
            add_res = cls._run_git(["add", "-A"], cwd=cwd, env=env, timeout=1.5)
            if add_res.returncode != 0:
                return results

            for msg_idx in message_indices:
                ref_name = cls.get_ref_name(session_id, msg_idx)
                rev_res = cls._run_git(["rev-parse", "--verify", ref_name], cwd=shadow_dir, timeout=0.2)
                if rev_res.returncode != 0:
                    continue
                commit_sha = rev_res.stdout.strip()

                diff_res = cls._run_git(["diff", "--cached", "--numstat", commit_sha], cwd=cwd, env=env, timeout=0.3)
                if diff_res.returncode != 0:
                    continue

                added, deleted = 0, 0
                for line in diff_res.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
                        added += int(parts[0])
                        deleted += int(parts[1])

                if added == 0 and deleted == 0:
                    results[msg_idx] = "no changes"
                else:
                    results[msg_idx] = f"+{added} / -{deleted}"

        return results

    @classmethod
    def delete_session_checkpoints(
        cls,
        session_id: str,
        project_path: Optional[str] = None,
    ) -> None:
        """Deletes all checkpoints for given session."""
        cls.purge_checkpoints_after(session_id, -1, project_path=project_path)

