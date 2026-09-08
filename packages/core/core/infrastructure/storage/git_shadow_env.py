import hashlib
import os
import time
import uuid
from contextlib import contextmanager
from typing import Generator, Optional

from core.infrastructure.platform.paths import SHADOW_REPOS_DIR


def ensure_shadow_exclude(
    shadow_dir: str, default_excludes: str, stale_lock_seconds: float = 30.0
) -> None:
    """Ensure .git/info/exclude has default exclusion patterns and clean stale locks."""
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
        for pattern in default_excludes.strip().splitlines():
            if pattern not in lines:
                new_lines.append(pattern)

        if new_lines:
            with open(exclude_file, "a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write("\n".join(new_lines) + "\n")
    except Exception:
        pass

    try:
        lock_file = os.path.join(shadow_dir, "index.lock")
        if os.path.exists(lock_file) and time.time() - os.path.getmtime(lock_file) > stale_lock_seconds:
            os.remove(lock_file)
    except Exception:
        pass


def base_shadow_env(shadow_dir: str, cwd: str, env_cache: dict[tuple[str, str], dict]) -> dict:
    """Build base environment variables for shadow git operations."""
    key = (shadow_dir, cwd)
    env = env_cache.get(key)
    if env is None:
        env = os.environ.copy()
        env["GIT_DIR"] = shadow_dir
        env["GIT_WORK_TREE"] = cwd
        env_cache[key] = env
    return env.copy()


@contextmanager
def shadow_index_env(shadow_dir: str, cwd: str, base_env_getter) -> Generator[dict, None, None]:
    """Temporary git index environment context manager."""
    tmp_index = os.path.join(shadow_dir, f"johnston_tmp_index_{os.getpid()}_{uuid.uuid4().hex[:8]}")
    env = base_env_getter(shadow_dir, cwd)
    env["GIT_INDEX_FILE"] = tmp_index
    try:
        yield env
    finally:
        if os.path.exists(tmp_index):
            try:
                os.remove(tmp_index)
            except Exception:
                pass


def get_shadow_dir(project_path: Optional[str] = None) -> tuple[str, str]:
    """Returns (shadow_repo_dir, canonical_cwd) for the given project path."""
    cwd = os.path.realpath(os.path.abspath(project_path or os.getcwd()))
    hash_id = hashlib.md5(cwd.encode("utf-8")).hexdigest()
    try:
        import core.infrastructure.storage.git_checkpoint as gcp

        base_dir = getattr(gcp, "SHADOW_REPOS_DIR", SHADOW_REPOS_DIR)
    except Exception:
        base_dir = SHADOW_REPOS_DIR
    shadow_dir = os.path.join(base_dir, f"{hash_id}.git")
    return shadow_dir, cwd
