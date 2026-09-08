"""Git info caching — branch detection with brief per-directory TTL cache."""

import asyncio
import os
import time
from typing import Dict, Optional, Tuple

_GIT_INFO_CACHE: Dict[str, Tuple[float, str]] = {}
_GIT_INFO_CACHE_TTL = 30.0


def _resolve_symbol(name: str):
    """Resolve a module symbol against the prompt_builder namespace first.

    Tests monkeypatch the private git symbols as
    ``core.application.generation.prompt_builder._compute_git_info`` and
    ``..._GIT_INFO_CACHE`` (dotted patch targets), so call-time lookups must
    see those replacements. This module's own globals are the fallback for
    standalone use (when prompt_builder was never imported).
    """
    import core.application.generation.prompt_builder as _pb

    return getattr(_pb, name, globals().get(name))


def _cached_git_info(cwd: Optional[str] = None) -> Optional[str]:
    """Return the cached git-info string for a directory, or None when stale/absent."""
    key = os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())
    cached = _resolve_symbol("_GIT_INFO_CACHE").get(key)
    if cached is not None and time.time() - cached[0] < _resolve_symbol("_GIT_INFO_CACHE_TTL"):
        return cached[1]
    return None


def _cache_git_info(cwd: Optional[str] = None, value: str = "") -> str:
    _resolve_symbol("_GIT_INFO_CACHE")[os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())] = (time.time(), value)
    return value


def get_git_info(cwd: str = None) -> str:
    """Returns current git branch for a working directory (defaults to os.getcwd()).

    Cached briefly per-directory so the multi-step agent loop does not spawn two
    git subprocesses on every tool-call step, and subagents report their own
    worktree branch instead of the parent checkout's.
    """
    key = os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())
    cached = _cached_git_info(key)
    if cached is not None:
        return cached

    last_known = _resolve_symbol("_GIT_INFO_CACHE").get(key, (0, ""))[1]

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        try:
            loop.create_task(get_git_info_async(cwd=cwd))
        except Exception:
            pass
        return last_known
    return _cache_git_info(key, _resolve_symbol("_compute_git_info")(cwd))


async def get_git_info_async(cwd: str = None) -> str:
    key = os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())
    cached = _cached_git_info(key)
    if cached is not None:
        return cached
    return _cache_git_info(key, await asyncio.to_thread(_resolve_symbol("_compute_git_info"), cwd))


def _compute_git_info(cwd: str = None) -> str:
    from core.infrastructure.runtime.git_utils import format_git_branch_info

    return format_git_branch_info(cwd=cwd)
