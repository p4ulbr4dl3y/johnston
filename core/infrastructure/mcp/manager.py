"""
MCP (Model Context Protocol) Manager for Johnston.
Handles global (~/.johnston/mcp.json) and project (.johnston/mcp.json) MCP servers.

Facade over the extracted components:
- ``MCPConfigLoader``  — config discovery + caching (``mcp/config_loader.py``)
- ``MCPClientPool``    — client lifecycle, start serialization, status (``mcp/client_pool.py``)
- ``MCPToolCatalog``   — tool naming/formatting (``mcp/tool_catalog.py``)
- ``MCPCallRouter``    — tool/resource/prompt call routing (``mcp/call_router.py``)
"""

import asyncio
import atexit
import logging
import os
import time
from typing import Any, Dict, List, Optional

from core.domain.defaults.config import DEFAULT_MCP_CALL_TIMEOUT
from core.infrastructure.mcp.call_router import MCPCallRouter
from core.infrastructure.mcp.client_pool import MCPClientPool
from core.infrastructure.mcp.config import GLOBAL_MCP_FILE, PROJECT_MCP_FILE
from core.infrastructure.mcp.config_loader import MCPConfigLoader
from core.infrastructure.mcp.process_client import MCPProcessClient
from core.infrastructure.mcp.schema import get_capabilities_for_exposed_tool, get_tool_capabilities
from core.infrastructure.mcp.tool_catalog import MCPToolCatalog
from core.infrastructure.platform.paths import CONFIG_DIR

logger = logging.getLogger(__name__)

_mcp_manager_instance: Optional["MCPManager"] = None
_atexit_registered = False


def _atexit_stop_all() -> None:
    inst = _mcp_manager_instance
    if inst is None:
        return
    try:
        inst.stop_all()
    except Exception:
        logger.debug("Failed to stop MCP manager at exit", exc_info=True)


def get_mcp_manager(project_dir: Optional[str] = None) -> "MCPManager":
    global _mcp_manager_instance, _atexit_registered
    if _mcp_manager_instance is None:
        _mcp_manager_instance = MCPManager(project_dir=project_dir)
    elif project_dir:
        real_p = os.path.realpath(project_dir)
        if _mcp_manager_instance.project_dir != real_p:
            _mcp_manager_instance.project_dir = real_p
            _mcp_manager_instance._config.set_project_dir(real_p)
            # The project switched: MCP processes launched with the old cwd are
            # no longer valid and would keep running with a stale working
            # directory. Stop them and drop cached tools so they are restarted
            # against the new project when next needed.
            _mcp_manager_instance._reset_clients_for_project()
    if not _atexit_registered:
        # Register the atexit hook exactly once (per instance registrations
        # multiplied the teardown pass and hit clients nobody owned).
        atexit.register(_atexit_stop_all)
        _atexit_registered = True
    return _mcp_manager_instance


class MCPManager:
    """Owns stdio MCP client processes plus global/project config discovery."""

    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_file = GLOBAL_MCP_FILE
        self.project_file = os.path.join(self.project_dir, PROJECT_MCP_FILE)
        # Registry + lifecycle state. Kept as plain instance attributes because
        # callers and tests mutate them directly; the extracted components
        # operate on them via ``self._mgr``.
        self.clients: Dict[str, Any] = {}
        self._server_errors: Dict[str, str] = {}
        self._start_locks: Dict[str, asyncio.Lock] = {}
        self._generation = 0
        self._tools_refresh_time = 0.0
        self._tools_refresh_task: Optional[asyncio.Task] = None
        self._listeners: List[Any] = []
        # Mirrors of config-loader state kept on the manager for direct reads
        # (tests/UI poke at these attributes).
        self._global_config_ensured = False
        self._warned_broken_config_files = set()
        # Extracted components (see module docstring). Created eagerly; the
        # ``__getattr__`` fallback additionally bootstraps instances built via
        # ``__new__`` in tests, which skip ``__init__``.
        self._config = MCPConfigLoader(self.project_dir)
        self._config.global_file = self.global_file
        self._config.project_file = self.project_file
        self._pool = MCPClientPool(self)
        self._catalog = MCPToolCatalog(self)
        self._router = MCPCallRouter(self)

    def __getattr__(self, name: str) -> Any:
        """Lazily create extracted components for ``__new__``-built instances."""
        if name == "_config" and self.__dict__.get("_config") is None:
            cfg = MCPConfigLoader(getattr(self, "project_dir", None))
            cfg.global_file = getattr(self, "global_file", cfg.global_file)
            cfg.project_file = getattr(self, "project_file", cfg.project_file)
            self.__dict__["_config"] = cfg
            return cfg
        if name == "_pool" and self.__dict__.get("_pool") is None:
            pool = MCPClientPool(self)
            self.__dict__["_pool"] = pool
            return pool
        if name == "_catalog" and self.__dict__.get("_catalog") is None:
            cat = MCPToolCatalog(self)
            self.__dict__["_catalog"] = cat
            return cat
        if name == "_router" and self.__dict__.get("_router") is None:
            rou = MCPCallRouter(self)
            self.__dict__["_router"] = rou
            return rou
        raise AttributeError(name)

    # -- observers -------------------------------------------------------------

    def add_listener(self, callback: Any) -> None:
        """Subscribe a callback to be notified on MCP state changes (warmup, tools, stop)."""
        if not hasattr(self, "_listeners"):
            self._listeners = []
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Any) -> None:
        """Unsubscribe a callback."""
        if hasattr(self, "_listeners") and callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self, event_type: str = "tools_updated") -> None:
        for cb in list(getattr(self, "_listeners", [])):
            try:
                cb(event_type)
            except Exception:
                logger.debug("MCPManager listener failed", exc_info=True)

    # -- lifecycle ----------------------------------------------------------------

    def stop_all(self):
        """Stops all running MCP client processes and cancels background warmup.

        Cancelling ``_tools_refresh_task`` matters: clients are registered in
        ``self.clients`` BEFORE their process starts, so every half-started
        client is stopped below even though the warmup task never completed.
        The generation bump makes any warmup coroutine still in flight abort
        before spawning a fresh process for the now-inactive manager.
        """
        task = self._tools_refresh_task
        if task is not None and not task.done():
            task.cancel()
        self._pool.stop_all()
        self._notify_listeners("stopped")

    async def stop_all_async(self):
        """Stops all running MCP client processes concurrently without blocking."""
        task = self._tools_refresh_task
        if task is not None and not task.done():
            task.cancel()
        await self._pool.stop_all_async()
        self._notify_listeners("stopped")

    def _reset_clients_for_project(self):
        """Stops and drops clients whose cwd belongs to a now-inactive project.

        Called when the manager's project_dir changes so stale MCP subprocesses
        (started with the previous project as their working directory) don't keep
        running. Also invalidates cached server/tool state so they are re-derived
        from the new project's config.
        """
        self._pool.stop_all()

    # -- config -------------------------------------------------------------------

    def _ensure_global_config(self) -> None:
        self._config._ensure_global_config()
        self._global_config_ensured = self._config._global_config_ensured

    def _warn_broken_config(self, path: str, reason: str = "") -> None:
        self._config.warn_broken_config(path, reason)
        self._warned_broken_config_files = self._config._warned_broken_config_files

    def _load_config_file(self, path: str, scope: str, servers: Dict[str, Dict[str, Any]]) -> None:
        from core.infrastructure.mcp.config import load_config_file

        load_config_file(path, scope, servers, self._config._warned_broken_config_files)
        # Keep the manager's alias in sync so tests reading it directly see
        # deduplicated warning entries.
        self._warned_broken_config_files = self._config._warned_broken_config_files

    def load_servers(self) -> List[Dict[str, Any]]:
        """
        Loads global and project MCP servers.
        Project servers override global servers with the same key.

        Results are cached by config file mtime/size so repeated calls (e.g. per
        tool call) do not re-read and re-parse JSON on every invocation. Cache is
        invalidated automatically when either config file changes, preserving
        hot-reload. The default global config is materialized lazily on first use.
        """
        cfg = self._config
        cfg.global_file = self.global_file
        cfg.project_file = self.project_file
        # Sync back loader state mirrors so direct attribute reads on the
        # manager always reflect the loader's dedup set / ensure flag.
        self._warned_broken_config_files = cfg._warned_broken_config_files
        self._global_config_ensured = cfg._global_config_ensured
        return cfg.load_servers()

    async def load_servers_async(self) -> List[Dict[str, Any]]:
        """Async variant of ``load_servers``: config-file reads run on a worker
        thread so they never block the event loop. Crash-miss path only —
        cache hits return instantly."""
        return await asyncio.to_thread(self.load_servers)

    def _update_server_config(self, name: str, key_updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Helper to read-modify-write MCP server config files atomically."""
        from core.infrastructure.mcp.config import update_server_config

        servers = self.load_servers()
        target = next((s for s in servers if s["name"] == name), None)
        if not target:
            return None
        try:
            update_server_config(self.global_file, self.project_file, target, name, key_updates)
        except Exception as e:
            logger.warning("Failed to update config for MCP server %s: %s", name, e)
        return target

    def toggle_server(self, name: str) -> bool:
        """
        Toggles enabled state of server by name.
        Saves updated state to the appropriate config file (project or global).
        Returns new enabled state (True = enabled, False = disabled).
        """
        servers = self.load_servers()
        target = next((s for s in servers if s["name"] == name), None)
        if not target:
            return False

        new_enabled = not self.server_enabled(target)
        if self._update_server_config(name, {"enabled": new_enabled}) is None:
            return False

        # Stop client if disabled. A deliberate disable is not a failure: any
        # remembered start error is dropped so re-enabling starts clean.
        if not new_enabled:
            self._pool.stop_client(name)

        self._notify_listeners("server_updated")
        return new_enabled

    @staticmethod
    def server_enabled(server: Dict[str, Any]) -> bool:
        from core.infrastructure.mcp.config import server_enabled

        return server_enabled(server)

    # -- tools ----------------------------------------------------------------------

    def get_active_tools(self) -> List[Dict[str, Any]]:
        """Connects to enabled MCP servers and returns their tools in OpenAI function format."""
        return self._catalog.get_active_tools()

    async def _load_server_tools_async(self, server: Dict[str, Any], timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Start (or refresh) a single MCP server and return its raw tools."""
        return await self._pool.load_server_tools_async(server, timeout=timeout)

    async def warm_server_async(self, name: str) -> None:
        """Start/refresh one enabled server immediately, bypassing warmup coalescing.

        Used by UI toggles: enabling a server must fetch its tools right away.
        The global warmup (``ensure_tools_ready_async``) skips spawning when a
        previous refresh finished inside its freshness window, which left a
        freshly-enabled server unstarted for up to 30s. Safe to run next to the
        global warmup: per-server start locks serialize client creation.
        """
        servers = await self.load_servers_async()
        target = next((s for s in servers if s.get("name") == name), None)
        if target is None or not self.server_enabled(target):
            return
        try:
            await self._load_server_tools_async(target)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Failed to warm MCP server %s", name, exc_info=True)
        finally:
            self._notify_listeners("server_updated")

    async def get_active_tools_async(self) -> List[Dict[str, Any]]:
        return await self._catalog.get_active_tools_async()

    def get_cached_tools(self) -> List[Dict[str, Any]]:
        """Return already discovered tools without starting processes or performing I/O."""
        return self._catalog.get_cached_tools()

    def get_tool_capabilities(self, server_name: str, tool_name: str) -> List[str]:
        return get_tool_capabilities(self.load_servers(), server_name, tool_name)

    def get_capabilities_for_exposed_tool(self, exposed_name: str) -> List[str]:
        return get_capabilities_for_exposed_tool(self.load_servers(), exposed_name)

    def get_system_prompt_snippet(self) -> str:
        from core.infrastructure.mcp.schema import format_system_prompt_snippet

        return format_system_prompt_snippet(self.get_cached_tools())

    # -- warmup coalescing --------------------------------------------------------------

    async def ensure_tools_ready_async(self, max_age: float = 30.0) -> List[Dict[str, Any]]:
        """Ensure MCP tools are being warmed up, coalescing concurrent callers.

        Never blocks the caller waiting for a cold (npx/uvx) server to start: it
        kicks off (or reuses) a background warmup task and returns the tools
        already cached from a previous run, so a later turn picks the freshly
        loaded tools up. A first call with an empty cache therefore returns []
        immediately while warmup proceeds in the background.

        A task that is still in flight is always reused — a fresh check is only
        spawned when the previous warmup finished longer than ``max_age`` ago.
        """
        now = time.monotonic()
        task = self._tools_refresh_task

        if task is not None and not task.done():
            # A warmup is already in flight: reuse it, never spawn a second
            # (spawning would orphan the first task and its done-callback).
            return self.get_cached_tools()

        if (now - self._tools_refresh_time) < max_age:
            # Most recent warmup finished within the freshness window.
            return self.get_cached_tools()

        task = asyncio.create_task(self.get_active_tools_async())
        self._tools_refresh_task = task

        def _on_done(done: asyncio.Task) -> None:
            self._tools_refresh_time = time.monotonic()
            if not done.cancelled():
                exc = done.exception()
                if exc:
                    logger.debug("Background MCP warmup failed: %s", exc)
            if self._tools_refresh_task is done:
                self._tools_refresh_task = None
            self._notify_listeners("warmup_complete")

        task.add_done_callback(_on_done)

        return self.get_cached_tools()

    def is_loading(self) -> bool:
        """True if background MCP server initialization or tool loading is currently in progress."""
        return self._tools_refresh_task is not None and not self._tools_refresh_task.done()

    def get_server_status(self, server_name: str) -> Dict[str, Any]:
        """Public, internals-free status snapshot for one MCP server (UI rendering)."""
        return self._pool.get_server_status(server_name)

    def active_server_count(self, servers: Optional[List[Dict[str, Any]]] = None) -> int:
        """Count enabled servers that finished loading tools without error.

        Pending/errored servers don't count, so while loading the footer flips
        to the spinner until the first warmup delivers tools.
        """
        if servers is None:
            servers = self.load_servers()
        count = 0
        for s in servers:
            if not self.server_enabled(s):
                continue
            st = self.get_server_status(s.get("name", ""))
            if st["tools"] > 0 and not st["error"]:
                count += 1
        return count

    # -- calls --------------------------------------------------------------------------

    def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        target_server: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """Executes an MCP tool call by name across active MCP clients."""
        return self._router.call_tool(tool_name, arguments, target_server=target_server, timeout=timeout)

    async def call_tool_async(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        target_server: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        return await self._router.call_tool_async(tool_name, arguments, target_server=target_server, timeout=timeout)

    async def get_active_resources_async(self, timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Returns all resources discovered across enabled MCP servers."""
        return await self._router.get_active_resources_async(timeout=timeout)

    async def read_resource_async(
        self, uri: str, server_name: Optional[str] = None, timeout: float = DEFAULT_MCP_CALL_TIMEOUT
    ) -> Optional[Dict[str, Any]]:
        """Reads an MCP resource by URI across enabled servers or from a target server."""
        return await self._router.read_resource_async(uri, server_name=server_name, timeout=timeout)

    async def get_active_prompts_async(self, timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Returns all prompts discovered across enabled MCP servers."""
        return await self._router.get_active_prompts_async(timeout=timeout)

    async def get_prompt_async(
        self,
        name: str,
        arguments: Optional[Dict[str, str]] = None,
        server_name: Optional[str] = None,
        timeout: float = DEFAULT_MCP_CALL_TIMEOUT,
    ) -> Optional[Dict[str, Any]]:
        """Gets prompt messages by prompt name."""
        return await self._router.get_prompt_async(name, arguments=arguments, server_name=server_name, timeout=timeout)

    # -- client creation ---------------------------------------------------------------

    def _create_client(self, server: Dict[str, Any]) -> Any:
        """Build and wire the right client (stdio subprocess or SSE) for a server entry."""
        name = server["name"]
        url = server.get("url")
        cwd = server.get("cwd") or self.project_dir
        env = server.get("env")
        if url:
            from core.infrastructure.mcp.sse_client import MCPSSEClient

            headers = server.get("headers")
            client = MCPSSEClient(name, url, headers=headers, cwd=cwd, env=env)
        else:
            cmd = server.get("command")
            args = server.get("args") or []
            full_cmd = [cmd] + list(args) if isinstance(cmd, str) else list(cmd) + list(args)
            client = MCPProcessClient(name, full_cmd, cwd=cwd, env=env)

        client.on_tools_changed = lambda: self._notify_listeners("tools_updated")
        client.on_resources_changed = lambda: self._notify_listeners("resources_updated")
        client.on_prompts_changed = lambda: self._notify_listeners("prompts_updated")
        return client

    def _tools_fetch_stale(self, server_name: str, ttl: float = 300.0) -> bool:
        return self._pool.tools_fetch_stale(server_name, ttl=ttl)

    def _resolve_target_client_and_tool(
        self, tool_name: str, active_tools: List[Dict[str, Any]], target_server: Optional[str] = None
    ):
        return self._router._resolve_target_client_and_tool(tool_name, active_tools, target_server=target_server)

    async def _teardown_unready_client(self, name: str, client: Any) -> None:
        await self._pool._teardown_unready_client(name, client)


__all__ = [
    "CONFIG_DIR",
    "GLOBAL_MCP_FILE",
    "MCPManager",
    "get_mcp_manager",
]
