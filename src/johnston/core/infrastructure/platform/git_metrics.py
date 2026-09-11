"""Git metrics — diff stats and branch info for UI status display.

Pure-core module (no Textual imports). Provides synchronous and async
helpers consumed by the TUI git_metrics mixin and status footer.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time

from johnston.core.dto.system import GitDiffDTO

_TTL = 2.0
# (ts, GitDiffDTO) per realpath; exported so tests can clear it.
_DIFF_METRICS_CACHE: dict[str, tuple[float, GitDiffDTO]] = {}
# (ts, changed_files) per realpath; exported so tests can clear it.
_GIT_SNAPSHOT_CACHE: dict[str, tuple[float, int]] = {}


def clear_git_metrics_cache() -> None:
    """Drop all module-level git metrics TTL caches (test hook)."""
    _DIFF_METRICS_CACHE.clear()
    _GIT_SNAPSHOT_CACHE.clear()


def _cache_key(cwd: str | None) -> str:
    return os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())


def get_diff_metrics(cwd: str | None = None) -> GitDiffDTO:
    """Return line-count insertions/deletions as GitDiffDTO vs HEAD.

    Memoized per-directory for TTL seconds so the footer refresh path
    (spinner ~3x/sec) does not re-fork git on every tick.
    """
    target_cwd = cwd or None
    key = ""
    cached = None
    try:
        key = _cache_key(target_cwd)
        cached = _DIFF_METRICS_CACHE.get(key)
        if cached is not None and time.time() - cached[0] < _TTL:
            return cached[1]
    except Exception:
        pass
    result = GitDiffDTO(insertions=0, deletions=0)
    try:
        res = subprocess.run(
            ["git", "diff", "HEAD", "--numstat"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=target_cwd,
        )
        if res.returncode != 0:
            res = subprocess.run(
                ["git", "diff", "--numstat"],
                capture_output=True,
                text=True,
                timeout=2,
                cwd=target_cwd,
            )
        if res.returncode == 0 and res.stdout.strip():
            adds = dels = 0
            for line in res.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                try:
                    adds += int(parts[0])
                    dels += int(parts[1])
                except ValueError:
                    pass
            result = GitDiffDTO(insertions=adds, deletions=dels)
    except Exception:
        pass
    try:
        _DIFF_METRICS_CACHE[key] = (time.time(), result)
    except Exception:
        pass
    return result


def get_changed_file_count(cwd: str | None = None) -> int:
    """Return the number of changed (untracked+modified) files via git status.

    Runs a single ``git status --porcelain`` (timeout=2s) and caches the
    count per-directory for TTL seconds so consecutive footer/status refreshes
    skip the fork. Returns 0 on any failure.
    """
    key = ""
    try:
        target_cwd = cwd or None
        key = _cache_key(target_cwd)
        cached = _GIT_SNAPSHOT_CACHE.get(key)
        if cached is not None and time.time() - cached[0] < _TTL:
            return cached[1]
    except Exception:
        pass
    count = 0
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=cwd or None,
        )
        if res.returncode == 0:
            lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
            count = len(lines)
    except Exception:
        pass
    try:
        _GIT_SNAPSHOT_CACHE[key] = (time.time(), count)
    except Exception:
        pass
    return count


def get_diff_stats(cwd: str | None = None) -> str:
    """Return ``"+N / -M"`` line-count diff vs HEAD, or ``""`` when unavailable."""
    diff = get_diff_metrics(cwd)
    if diff.insertions or diff.deletions:
        return f"+{diff.insertions} / -{diff.deletions}"
    return ""


async def get_diff_stats_async(cwd: str | None = None) -> str:
    """Async wrapper around :func:`get_diff_stats`."""
    return await asyncio.to_thread(get_diff_stats, cwd)


def get_branch_info(cwd: str | None = None) -> str:
    """Return the current branch name or ``""`` when not in a repo.

    Reuses the cached :func:`get_git_info` from the generation layer and
    applies the same *detached HEAD → detached* formatting used by the
    TUI footer.
    """
    try:
        from johnston.core.application.generation.prompt_builder import get_git_info

        target_cwd = cwd or None
        info = (get_git_info(cwd=target_cwd) or "").strip()
        if info.startswith("detached HEAD"):
            info = info.replace("detached HEAD (", "detached (")
        return info
    except Exception:
        pass
    return ""
