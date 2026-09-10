"""Git metrics — diff stats and branch info for UI status display.

Pure-core module (no Textual imports). Provides synchronous and async
helpers consumed by the TUI git_metrics mixin and status footer.
"""

from __future__ import annotations

import asyncio
import subprocess

from johnston.core.dto.system import GitDiffDTO


def get_diff_metrics(cwd: str | None = None) -> GitDiffDTO:
    """Return line-count insertions/deletions as GitDiffDTO vs HEAD."""
    try:
        target_cwd = cwd or None

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
            return GitDiffDTO(insertions=adds, deletions=dels)
    except Exception:
        pass
    return GitDiffDTO(insertions=0, deletions=0)


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
