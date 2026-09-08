"""MCP server config discovery: global + project file loading with caching.

Keeps the config concerns out of ``MCPManager``: parsing/validation lives in
``core.infrastructure.mcp.config``, this module owns the project-aware file
resolution, the mtime/size signature cache and the lazily materialized default
global config.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from johnston_core.infrastructure.mcp.config import (
    GLOBAL_MCP_FILE,
    PROJECT_MCP_FILE,
    ensure_global_config,
    load_config_file,
    servers_signature,
)

logger = logging.getLogger(__name__)


class MCPConfigLoader:
    """Loads and caches the merged global/project MCP server list.

    Project servers override global servers with the same key. Results are
    cached by config-file mtime/size so repeated calls (e.g. per tool call) do
    not re-read and re-parse JSON on every invocation; the cache invalidates
    automatically when either file changes. The default global config is
    materialized lazily on first use, never in the constructor.
    """

    def __init__(self, project_dir: Optional[str] = None) -> None:
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_file = GLOBAL_MCP_FILE
        self.project_file = os.path.join(self.project_dir, PROJECT_MCP_FILE)
        self._servers_cache_signature: Optional[Tuple] = None
        self._servers_cache: List[Dict[str, Any]] = []
        self._warned_broken_config_files = set()
        self._global_config_ensured = False

    def set_project_dir(self, project_dir: str) -> None:
        """Point the loader at a new project; the cache is dropped on next load."""
        self.project_dir = os.path.realpath(project_dir)
        self.project_file = os.path.join(self.project_dir, PROJECT_MCP_FILE)
        self._servers_cache_signature = None
        self._servers_cache = []

    def _ensure_global_config(self) -> None:
        ensure_global_config(self.global_file)
        self._global_config_ensured = True

    def _servers_signature(self) -> Tuple:
        return servers_signature(self.global_file, self.project_file)

    def warn_broken_config(self, path: str, reason: str = "") -> None:
        """One-time warning per (path, reason); keeps the shared dedup set."""
        from johnston_core.infrastructure.mcp.config import warn_broken_config

        warn_broken_config(self._warned_broken_config_files, path, reason)

    def load_servers(self) -> List[Dict[str, Any]]:
        """Merged global + project servers, cached by config file signature."""
        curr_proj_dir = os.path.realpath(self.project_dir or os.getcwd())
        self.project_file = os.path.join(curr_proj_dir, PROJECT_MCP_FILE)
        if not self._global_config_ensured:
            self._ensure_global_config()

        signature = self._servers_signature()
        if signature == self._servers_cache_signature:
            return list(self._servers_cache)

        servers: Dict[str, Dict[str, Any]] = {}
        load_config_file(self.global_file, "global", servers, self._warned_broken_config_files)

        real_global = os.path.realpath(self.global_file)
        real_project = os.path.realpath(self.project_file)
        if os.path.exists(self.project_file) and real_project != real_global:
            load_config_file(self.project_file, "project", servers, self._warned_broken_config_files)

        self._servers_cache = list(servers.values())
        self._servers_cache_signature = signature
        return list(self._servers_cache)

    async def load_servers_async(self) -> List[Dict[str, Any]]:
        """Async variant of ``load_servers``: file reads run on a worker thread.

        Crash-miss path only — cache hits return instantly.
        """
        return await asyncio.to_thread(self.load_servers)


__all__ = ["MCPConfigLoader"]
