"""
MCP (Model Context Protocol) Manager for Johnston.
Handles global (~/.johnston/mcp.json) and project (.johnston/mcp.json) MCP servers.
"""

import asyncio
import atexit
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from core.domain.defaults.config import DEFAULT_MCP_CALL_TIMEOUT
from core.infrastructure.mcp.config import (
    GLOBAL_MCP_FILE,
    PROJECT_MCP_FILE,
    command_parts_valid,
    ensure_global_config,
    load_config_file,
    server_enabled,
    servers_signature,
    update_server_config,
    warn_broken_config,
)
from core.infrastructure.mcp.process_client import MCPProcessClient
from core.infrastructure.mcp.schema import (
    format_system_prompt_snippet,
    format_tool_schema,
    get_capabilities_for_exposed_tool,
    get_tool_capabilities,
)
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
            _mcp_manager_instance.project_file = os.path.join(real_p, PROJECT_MCP_FILE)
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
        self.clients: Dict[str, MCPProcessClient] = {}
        self._tools_refresh_time = 0.0
        self._tools_refresh_task: Optional[asyncio.Task] = None
        self._servers_cache_signature: Optional[Tuple] = None
        self._servers_cache: List[Dict[str, Any]] = []
        self._warned_broken_config_files = set()
        self._global_config_ensured = False
        # Per-server locks serializing client creation so two concurrent warmup
        # callers (lifecycle mount, MCP/permissions screens, registry fallback)
        # can never spawn two npx processes for the same server. Lazily created
        # on first use; the create-then-store is atomic in a single loop so no
        # two callers can race to build a duplicate lock.
        self._start_locks: Dict[str, asyncio.Lock] = {}
        # Incremented by ``stop_all``: in-flight warmup coroutines capture the
        # generation before starting a server and abort if it changed, so a
        # stopped manager can never re-spawn clients for a dead project.
        self._generation = 0
        # Last fatal start error per server. A client that failed to start is
        # torn down and popped from ``clients``, which would otherwise lose its
        # ``last_error``; the UI reads this map via ``get_server_status`` to
        # keep showing ERR/Timeout badges after a failed warmup.
        self._server_errors: Dict[str, str] = {}
        self._listeners: List[Any] = []

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

    def stop_all(self):
        """Stops all running MCP client processes and cancels background warmup.

        Cancelling ``_tools_refresh_task`` matters: clients are registered in
        ``self.clients`` BEFORE their process starts, so every half-started
        client is stopped below even though the warmup task never completed.
        The generation bump makes any warmup coroutine still in flight abort
        before spawning a fresh process for the now-inactive manager.
        """
        self._generation += 1
        self._start_locks.clear()
        self._server_errors.clear()
        task = self._tools_refresh_task
        if task is not None and not task.done():
            task.cancel()
        for client in list(self.clients.values()):
            stop = getattr(client, "stop", None)
            if not callable(stop):
                continue
            try:
                stop()
            except Exception:
                logger.warning("Failed to stop MCP client", exc_info=True)
        self.clients.clear()
        self._notify_listeners("stopped")

    async def stop_all_async(self):
        """Stops all running MCP client processes concurrently without blocking."""
        self._generation += 1
        self._start_locks.clear()
        self._server_errors.clear()
        task = self._tools_refresh_task
        if task is not None and not task.done():
            task.cancel()
        clients = list(self.clients.values())
        self.clients.clear()
        if clients:
            coros = []
            for client in clients:
                stop_async = getattr(client, "stop_async", None)
                if callable(stop_async):
                    coros.append(stop_async())
                else:
                    stop = getattr(client, "stop", None)
                    if callable(stop):
                        coros.append(asyncio.to_thread(stop))
            if coros:
                await asyncio.gather(*coros, return_exceptions=True)
        self._notify_listeners("stopped")

    def _reset_clients_for_project(self):
        """Stops and drops clients whose cwd belongs to a now-inactive project.

        Called when the manager's project_dir changes so stale MCP subprocesses
        (started with the previous project as their working directory) don't keep
        running. Also invalidates cached server/tool state so they are re-derived
        from the new project's config.
        """
        self.stop_all()
        self._servers_cache_signature = None
        self._servers_cache = []

    def _ensure_global_config(self) -> None:
        ensure_global_config(self.global_file)
        self._global_config_ensured = True

    def _warn_once(self, key: Tuple[str, str], message: str) -> None:
        if key in self._warned_broken_config_files:
            return
        self._warned_broken_config_files.add(key)
        logger.warning("%s", message)

    def _warn_broken_config(self, path: str, reason: str = "") -> None:
        warn_broken_config(self._warned_broken_config_files, path, reason)

    @staticmethod
    def server_enabled(server: Dict[str, Any]) -> bool:
        return server_enabled(server)

    @staticmethod
    def _command_parts_valid(cmd: Any) -> bool:
        return command_parts_valid(cmd)

    def _servers_signature(self) -> Tuple:
        return servers_signature(self.global_file, self.project_file)

    def _tools_fetch_stale(self, server_name: str, ttl: float = 300.0) -> bool:
        client = self.clients.get(server_name)
        if client is None:
            return False
        return bool(client.is_tools_stale(ttl=ttl))

    def _load_config_file(self, path: str, scope: str, servers: Dict[str, Dict[str, Any]]) -> None:
        load_config_file(path, scope, servers, self._warned_broken_config_files)

    def load_servers(self) -> List[Dict[str, Any]]:
        """
        Loads global and project MCP servers.
        Project servers override global servers with the same key.

        Results are cached by config file mtime/size so repeated calls (e.g. per
        tool call) do not re-read and re-parse JSON on every invocation. Cache is
        invalidated automatically when either config file changes, preserving
        hot-reload. The default global config is materialized lazily on first use.
        """
        curr_proj_dir = os.path.realpath(self.project_dir or os.getcwd())
        self.project_file = os.path.join(curr_proj_dir, PROJECT_MCP_FILE)
        if not self._global_config_ensured:
            self._ensure_global_config()

        signature = self._servers_signature()
        if signature == self._servers_cache_signature:
            return list(self._servers_cache)

        servers: Dict[str, Dict[str, Any]] = {}
        self._load_config_file(self.global_file, "global", servers)

        real_global = os.path.realpath(self.global_file)
        real_project = os.path.realpath(self.project_file)
        if os.path.exists(self.project_file) and real_project != real_global:
            self._load_config_file(self.project_file, "project", servers)

        self._servers_cache = list(servers.values())
        self._servers_cache_signature = signature
        return list(self._servers_cache)

    async def load_servers_async(self) -> List[Dict[str, Any]]:
        """Async variant of ``load_servers``: config-file reads run on a worker
        thread so they never block the event loop. Crash-miss path only —
        cache hits return instantly."""
        return await asyncio.to_thread(self.load_servers)

    def _update_server_config(self, name: str, key_updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Helper to read-modify-write MCP server config files atomically."""
        servers = self.load_servers()
        target = next((s for s in servers if s["name"] == name), None)
        if not target:
            return None
        try:
            update_server_config(self.global_file, self.project_file, target, name, key_updates)
        except Exception as e:
            logger.warning("Failed to update config for MCP server %s: %s", name, e)
        return target

    def _format_tool_schema(self, tool: Dict[str, Any], server_name: str, seen_names: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Formats tool dict to OpenAI function format and handles name collisions across servers."""
        return format_tool_schema(tool, server_name, seen_names)

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

        # Stop client if disabled
        if not new_enabled and name in self.clients:
            self.clients[name].stop()
            del self.clients[name]
        if not new_enabled:
            # Deliberate disable is not a failure: drop any remembered start
            # error so re-enabling starts with a clean status.
            self._server_errors.pop(name, None)

        self._notify_listeners("server_updated")
        return new_enabled

    def _create_client(self, server: Dict[str, Any]) -> Any:
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

    def get_active_tools(self) -> List[Dict[str, Any]]:
        """Connects to enabled MCP servers and returns their tools in OpenAI function format."""
        tools: List[Dict[str, Any]] = []
        servers = self.load_servers()
        seen_names: Dict[str, str] = {}  # tool_name -> server_name

        for s in servers:
            if not self.server_enabled(s):
                continue

            name = s["name"]
            url = s.get("url")
            cmd = s.get("command")
            if not url and not cmd:
                continue

            client = self.clients.get(name)
            if not client:
                client = self._create_client(s)
                if client.start():
                    self.clients[name] = client
                    self._server_errors.pop(name, None)
                else:
                    err = getattr(client, "last_error", None)
                    if err:
                        self._server_errors[name] = err
                    continue
            else:
                if self._tools_fetch_stale(name):
                    try:
                        client.fetch_tools()
                    except Exception:
                        logger.warning("Failed to fetch tools for MCP server %s", name, exc_info=True)

            for t in getattr(client, "tools", []):
                formatted = self._format_tool_schema(t, name, seen_names)
                if formatted:
                    tools.append(formatted)

        return tools

    async def _load_server_tools_async(self, server: Dict[str, Any], timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Start (or refresh) a single MCP server and return its raw tools.

        Isolated per server with a short deadline so one slow/broken server can
        never block the others: any failure yields an empty list for that server
        only. A per-server lock serializes client creation: concurrent callers
        (lifecycle mount, MCP/permissions screens, registry fallback) share the
        first spawned process instead of double-starting npx. Clients are
        registered BEFORE their subprocess starts so ``stop_all`` can always
        reach and terminate a half-started server. Naming/formatting happens
        later, sequentially, so name-collision assignment stays deterministic.
        """
        name = server["name"]
        url = server.get("url")
        cmd = server.get("command")
        if not url and not cmd:
            return []

        gen = self._generation
        lock = self._start_locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            self._start_locks[name] = lock

        async with lock:
            if self._generation != gen:
                # The manager was stopped while we waited for the lock: spawning
                # a client now would resurrect processes for a dead project.
                return []

            client = self.clients.get(name)
            created = client is None
            if created:
                client = self._create_client(server)
                # Register before starting: a concurrent stop_all() iterates
                # clients, so a half-started process must already be reachable.
                self.clients[name] = client

            try:
                if created:
                    try:
                        ok = await asyncio.wait_for(client.start_async(), timeout=timeout)
                    except asyncio.TimeoutError:
                        client.last_error = client.last_error or f"Server start timed out after {timeout}s"
                        await self._teardown_unready_client(name, client)
                        return []
                    except asyncio.CancelledError:
                        # The surrounding warmup task was cancelled (e.g. by
                        # stop_all): never orphan the spawned subprocess.
                        await self._teardown_unready_client(name, client)
                        raise
                    except Exception as exc:
                        if not client.last_error:
                            client.last_error = str(exc)
                        await self._teardown_unready_client(name, client)
                        return []
                    if not ok:
                        if not client.last_error:
                            client.last_error = "Failed to start"
                        await self._teardown_unready_client(name, client)
                        return []
                    if self._generation != gen:
                        await self._teardown_unready_client(name, client)
                        return []
                    # A previous failed attempt may have left a remembered
                    # error; the server now started cleanly.
                    self._server_errors.pop(name, None)
                elif self._tools_fetch_stale(name):
                    try:
                        await asyncio.wait_for(client.fetch_tools_async(), timeout=timeout)
                    except Exception:
                        logger.warning("Failed to fetch tools asynchronously for MCP server %s", name, exc_info=True)

                return list(client.tools)
            except Exception:
                logger.warning("MCP server %s failed to load tools", name, exc_info=True)
                return []

    async def _teardown_unready_client(self, name: str, client: Any) -> None:
        """Stop a client that must not stay alive and drop it from the cache.

        Remembering its fatal ``last_error`` keeps the UI showing an ERR badge
        after a failed start instead of a bare ON row — but only when this
        attempt still owns the cache slot (see the guard below).
        """
        try:
            await client.stop_async()
        except Exception:
            logger.debug("Failed to stop unready MCP client %s", name, exc_info=True)
        finally:
            # The spawned process itself must always be stopped above, but the
            # shared caches are only mutated when this attempt still owns the
            # slot: a stale attempt that lost the post-start generation race
            # (stop_all + a newer successful warmup) would otherwise pop the
            # replacement client — leaking its live subprocess — and overwrite
            # the fresh server's clean status with its own remembered error.
            if self.clients.get(name) is client:
                err = getattr(client, "last_error", None)
                if err:
                    self._server_errors[name] = err
                self.clients.pop(name, None)

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
        servers = await self.load_servers_async()
        eligible = [
            s for s in servers if self.server_enabled(s) and (s.get("command") or s.get("url"))
        ]
        # Start every server concurrently with an isolated per-server deadline so
        # a slow/cold (npx/uvx) or broken server cannot stall the others. Tool
        # naming/formatting happens afterwards, sequentially in config order, so
        # the winner of a name collision is deterministic (config order), not
        # whatever gather scheduling happened to finish first.
        results = await asyncio.gather(*(self._load_server_tools_async(s) for s in eligible), return_exceptions=True)

        tools: List[Dict[str, Any]] = []
        seen_names: Dict[str, str] = {}
        for server, res in zip(eligible, results):
            if isinstance(res, Exception):
                logger.debug("MCP server %s failed to load tools: %s", server.get("name"), res)
                continue
            for t in res or []:
                formatted = self._format_tool_schema(t, server["name"], seen_names)
                if formatted:
                    tools.append(formatted)
        return tools

    def get_cached_tools(self) -> List[Dict[str, Any]]:
        """Return already discovered tools without starting processes or performing I/O."""
        tools: List[Dict[str, Any]] = []
        seen_names: Dict[str, str] = {}

        for server in self.load_servers():
            if not self.server_enabled(server):
                continue

            server_name = server.get("name", "")
            client = self.clients.get(server_name)
            if client is None:
                continue

            for tool in client.tools:
                formatted = self._format_tool_schema(tool, server_name, seen_names)
                if formatted:
                    tools.append(formatted)

        return tools

    def get_server_status(self, server_name: str) -> Dict[str, Any]:
        """Public, internals-free status snapshot for one MCP server (UI rendering).

        Returns the discovered tool count, last error and whether the client
        process is running. UI layers should use this instead of poking at
        ``clients`` / ``client.tools`` / ``client.last_error`` directly. Errors
        from failed starts survive client teardown via the per-server error map.
        """
        stored_err = self._server_errors.get(server_name)
        client = self.clients.get(server_name)
        if client is None:
            return {"server": server_name, "tools": 0, "error": stored_err, "running": False}
        proc = getattr(client, "process", None)
        running = False
        if proc is not None:
            try:
                running = proc.poll() is None
            except Exception:
                running = False
        err = getattr(client, "last_error", None) or stored_err
        tools = getattr(client, "tools", None) or []
        return {"server": server_name, "tools": len(tools), "error": err, "running": running}

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

    def get_tool_capabilities(self, server_name: str, tool_name: str) -> List[str]:
        return get_tool_capabilities(self.load_servers(), server_name, tool_name)

    def get_capabilities_for_exposed_tool(self, exposed_name: str) -> List[str]:
        return get_capabilities_for_exposed_tool(self.load_servers(), exposed_name)

    def _resolve_target_client_and_tool(
        self, tool_name: str, active_tools: List[Dict[str, Any]], target_server: Optional[str] = None
    ) -> Tuple[Optional[MCPProcessClient], Optional[str]]:
        """Helper to match exposed or raw tool_name against active MCP clients."""
        for t in active_tools:
            s_name = t.get("_mcp_server")
            o_name = t.get("_mcp_tool_name")
            if s_name is None or o_name is None:
                continue
            if target_server and s_name != target_server:
                continue
            exposed_name = t.get("function", {}).get("name")
            if exposed_name == tool_name or o_name == tool_name:
                client = self.clients.get(s_name)
                if client:
                    return client, o_name

        return None, None

    def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        target_server: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """Executes an MCP tool call by name across active MCP clients."""
        if timeout is None:
            try:
                from core.infrastructure.config.settings import get_settings

                timeout = get_settings().tools.mcp_call_timeout
            except Exception:
                timeout = DEFAULT_MCP_CALL_TIMEOUT

        if target_server and target_server in self.clients:
            client = self.clients[target_server]
            raw_name = tool_name[len(target_server) + 2 :] if tool_name.startswith(f"{target_server}__") else tool_name
            return client.call_tool(raw_name, arguments, timeout=timeout)

        active_tools = self.get_active_tools()
        client, o_name = self._resolve_target_client_and_tool(tool_name, active_tools, target_server=target_server)
        if client and o_name:
            return client.call_tool(o_name, arguments, timeout=timeout)
        return None

    async def call_tool_async(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        target_server: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        if timeout is None:
            try:
                from core.infrastructure.config.settings import get_settings

                timeout = get_settings().tools.mcp_call_timeout
            except Exception:
                timeout = DEFAULT_MCP_CALL_TIMEOUT

        if target_server and target_server in self.clients:
            client = self.clients[target_server]
            raw_name = tool_name[len(target_server) + 2 :] if tool_name.startswith(f"{target_server}__") else tool_name
            return await client.call_tool_async(raw_name, arguments, timeout=timeout)

        active_tools = await self.get_active_tools_async()
        client, o_name = self._resolve_target_client_and_tool(tool_name, active_tools, target_server=target_server)
        if client and o_name:
            return await client.call_tool_async(o_name, arguments, timeout=timeout)
        return None

    async def get_active_resources_async(self, timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Returns all resources discovered across enabled MCP servers."""
        resources: List[Dict[str, Any]] = []
        servers = await self.load_servers_async()
        for s in servers:
            if not self.server_enabled(s):
                continue
            name = s["name"]
            await self._load_server_tools_async(s, timeout=timeout)
            client = self.clients.get(name)
            if client and hasattr(client, "resources"):
                for r in client.resources:
                    r_copy = dict(r)
                    r_copy["_mcp_server"] = name
                    resources.append(r_copy)
        return resources

    async def read_resource_async(
        self, uri: str, server_name: Optional[str] = None, timeout: float = DEFAULT_MCP_CALL_TIMEOUT
    ) -> Optional[Dict[str, Any]]:
        """Reads an MCP resource by URI across enabled servers or from a target server."""
        if server_name and server_name in self.clients:
            client = self.clients[server_name]
            if hasattr(client, "read_resource_async"):
                return await client.read_resource_async(uri, timeout=timeout)

        active_resources = await self.get_active_resources_async(timeout=timeout)
        for r in active_resources:
            if r.get("uri") == uri:
                s_name = r.get("_mcp_server")
                client = self.clients.get(s_name)
                if client and hasattr(client, "read_resource_async"):
                    return await client.read_resource_async(uri, timeout=timeout)

        for client in self.clients.values():
            if hasattr(client, "read_resource_async"):
                try:
                    res = await client.read_resource_async(uri, timeout=timeout)
                    if res:
                        return res
                except Exception:
                    pass
        return None

    async def get_active_prompts_async(self, timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Returns all prompts discovered across enabled MCP servers."""
        prompts: List[Dict[str, Any]] = []
        servers = await self.load_servers_async()
        for s in servers:
            if not self.server_enabled(s):
                continue
            name = s["name"]
            await self._load_server_tools_async(s, timeout=timeout)
            client = self.clients.get(name)
            if client and hasattr(client, "prompts"):
                for p in client.prompts:
                    p_copy = dict(p)
                    p_copy["_mcp_server"] = name
                    prompts.append(p_copy)
        return prompts

    async def get_prompt_async(
        self,
        name: str,
        arguments: Optional[Dict[str, str]] = None,
        server_name: Optional[str] = None,
        timeout: float = DEFAULT_MCP_CALL_TIMEOUT,
    ) -> Optional[Dict[str, Any]]:
        """Gets prompt messages by prompt name."""
        if server_name and server_name in self.clients:
            client = self.clients[server_name]
            if hasattr(client, "get_prompt_async"):
                return await client.get_prompt_async(name, arguments=arguments, timeout=timeout)

        active_prompts = await self.get_active_prompts_async(timeout=timeout)
        for p in active_prompts:
            if p.get("name") == name:
                s_name = p.get("_mcp_server")
                client = self.clients.get(s_name)
                if client and hasattr(client, "get_prompt_async"):
                    return await client.get_prompt_async(name, arguments=arguments, timeout=timeout)

        for client in self.clients.values():
            if hasattr(client, "get_prompt_async"):
                try:
                    res = await client.get_prompt_async(name, arguments=arguments, timeout=timeout)
                    if res:
                        return res
                except Exception:
                    pass
        return None

    def get_system_prompt_snippet(self) -> str:
        return format_system_prompt_snippet(self.get_cached_tools())


__all__ = [
    "CONFIG_DIR",
    "GLOBAL_MCP_FILE",
    "MCPManager",
    "get_mcp_manager",
]


