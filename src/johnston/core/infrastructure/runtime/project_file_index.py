import asyncio
import logging
import os
import subprocess
import time
from typing import List, Optional, Set

from johnston.core.domain.defaults.git_excludes import DEFAULT_BINARY_EXTENSIONS, DEFAULT_IGNORE_DIRS

logger = logging.getLogger(__name__)


class ProjectFileIndex:
    """Fast, cached file index for autocomplete (@file) with git integration."""

    _instance: Optional["ProjectFileIndex"] = None

    def __init__(self, ttl: float = 20.0):
        self._ttl = ttl
        self._cached_files: List[str] = []
        self._cached_cwd: str = ""
        self._cache_time: float = 0.0
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "ProjectFileIndex":
        if cls._instance is None:
            cls._instance = ProjectFileIndex()
        return cls._instance

    def scan_sync(self, cwd: str, max_files: int = 1000) -> List[str]:
        """Synchronously scan workspace using git ls-files if available, falling back to os.walk."""
        files_list: List[str] = []
        real_cwd = os.path.realpath(cwd)
        home = os.path.realpath(os.path.expanduser("~"))
        is_home_or_root = real_cwd == home or os.path.dirname(real_cwd) == real_cwd

        effective_limit = min(300, max_files) if is_home_or_root else max_files

        # 1. Fast path: git repository
        git_dir = os.path.join(cwd, ".git")
        if not is_home_or_root and (os.path.isdir(git_dir) or os.path.isfile(git_dir)):
            try:
                out = subprocess.check_output(
                    ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                    cwd=cwd,
                    timeout=1.5,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                git_dirs: Set[str] = set()
                for line in out.splitlines():
                    clean_line = line.strip().replace("\\", "/")
                    if not clean_line:
                        continue
                    ext = clean_line.rsplit(".", 1)[-1].lower() if "." in clean_line else ""
                    if ext in DEFAULT_BINARY_EXTENSIONS or ext == "pyc":
                        continue
                    files_list.append(clean_line)
                    parts = clean_line.split("/")
                    for i in range(1, len(parts)):
                        git_dirs.add("/".join(parts[:i]) + "/")
                    if len(files_list) >= effective_limit:
                        break
                files_list.extend(git_dirs)
                if files_list:
                    return sorted(set(files_list))[:effective_limit]
            except Exception:
                files_list.clear()

        # 2. Fallback path: directory walk honoring DEFAULT_IGNORE_DIRS
        ignore_dirs = set(DEFAULT_IGNORE_DIRS) | {
            ".idea",
            ".vscode",
            ".gemini",
            ".cache",
            "Library",
            ".Trash",
            "Applications",
            "Pictures",
            "Movies",
            "Music",
        }

        try:
            for root, dirs, files in os.walk(cwd):
                rel_dir = os.path.relpath(root, cwd)
                depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
                if is_home_or_root and depth >= 2:
                    dirs.clear()
                    continue

                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                for d in dirs:
                    rel_path = d if rel_dir == "." else os.path.join(rel_dir, d)
                    files_list.append(rel_path.replace("\\", "/") + "/")
                    if len(files_list) >= effective_limit:
                        break

                for f in files:
                    if f.startswith(".") or f.endswith(".pyc"):
                        continue
                    ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                    if ext in DEFAULT_BINARY_EXTENSIONS:
                        continue
                    rel_path = f if rel_dir == "." else os.path.join(rel_dir, f)
                    files_list.append(rel_path.replace("\\", "/"))
                    if len(files_list) >= effective_limit:
                        break

                if len(files_list) >= effective_limit:
                    break
        except Exception:
            pass

        return sorted(set(files_list))[:effective_limit]

    async def get_files(self, cwd: Optional[str] = None, max_files: int = 1000) -> List[str]:
        target_cwd = cwd or os.getcwd()
        now = time.time()
        if (
            self._cached_files
            and self._cached_cwd == target_cwd
            and (now - self._cache_time) < self._ttl
        ):
            return self._cached_files

        async with self._lock:
            # Double check after acquiring lock
            if (
                self._cached_files
                and self._cached_cwd == target_cwd
                and (now - self._cache_time) < self._ttl
            ):
                return self._cached_files

            files = await asyncio.to_thread(self.scan_sync, target_cwd, max_files)
            self._cached_files = files
            self._cached_cwd = target_cwd
            self._cache_time = time.time()
            return self._cached_files

    def invalidate(self) -> None:
        self._cached_files = []
        self._cached_cwd = ""
        self._cache_time = 0.0
