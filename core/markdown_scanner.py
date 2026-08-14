"""Shared Markdown directory scanning with TTL+signature caching.

Roles, rules (and historically skills) all need the same primitive: scan a
``global + project/.johnston/<subpath>`` set of directories for ``*.md`` files,
detect disk changes via a cheap ``(path, mtime_ns, size)`` signature, and cache
the parsed result for a short TTL. This module owns that duplicated concern so
each manager only supplies how to turn discovered files into its own result type.
"""

import os
import time
from typing import Any, Callable, List, Optional, Tuple

from core.config import CONFIG_DIR
from core.frontmatter import iter_md_files
from core.fs_signature import compute_dir_signature

_CACHE_TTL = 2.0  # seconds

MarkdownDirs = List[Tuple[str, str]]
MarkdownScanResult = Tuple[Optional[Tuple], MarkdownDirs]


def build_markdown_dirs(
    project_dir: Optional[str] = None,
    include_global: bool = True,
    subpath: str = "roles",
    config_dir: Optional[str] = None,
) -> MarkdownDirs:
    """Return ``[(dir, source), ...]`` for the global and project markdown trees."""
    config_dir = config_dir or CONFIG_DIR
    p_dir = project_dir or os.getcwd()
    dirs: MarkdownDirs = []
    if include_global:
        dirs.append((os.path.join(config_dir, subpath), "global"))
    dirs.append((os.path.join(p_dir, ".johnston", subpath), "project"))
    return dirs


class MarkdownScannerCache:
    """TTL+signature cache around a markdown directory scan.

    ``build(dirs, files)`` is called on a miss with the resolved directory list
    and the list of ``(path, source)`` files to produce a manager-specific result.
    """

    @property
    def cache_ttl(self) -> float:
        return _CACHE_TTL

    def __init__(self, subpath: str = "roles"):
        self.subpath = subpath
        self._signature: Optional[Tuple] = None
        self._ts: float = 0.0
        self._value: Any = None

    def get(
        self,
        project_dir: Optional[str] = None,
        include_global: bool = True,
        build: Optional[Callable[[MarkdownDirs, List[Tuple[str, str]]], Any]] = None,
    ) -> Any:
        dirs = build_markdown_dirs(project_dir, include_global=include_global, subpath=self.subpath)
        signature = compute_dir_signature(dirs, [".md", ".markdown"]) or ()
        now = time.time()
        if (
            self._signature is not None
            and signature == self._signature
            and (now - self._ts) < self.cache_ttl
        ):
            return self._value
        files = list(iter_md_files(dirs))
        value = build(dirs, files) if build else files
        self._signature = signature
        self._ts = now
        self._value = value
        return value

    def invalidate(self) -> None:
        """Force the next ``get`` to re-scan from disk."""
        self._signature = None
        self._ts = 0.0
