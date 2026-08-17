"""
MCP (Model Context Protocol) Manager for Johnston.
Handles global (~/.johnston/mcp.json) and project (.johnston/mcp.json) MCP servers.
"""

import asyncio
import atexit
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from core.infrastructure.mcp.process_client import MCPProcessClient
from core.infrastructure.platform.paths import CONFIG_DIR
from core.infrastructure.platform.platform_utils import atomic_write_json

logger = logging.getLogger(__name__)

GLOBAL_MCP_FILE = os.path.join(CONFIG_DIR, "mcp.json")
PROJECT_MCP_FILE = os.path.join(".johnston", "mcp.json")

# Default upper bound for an MCP tools/call round-trip. A hanging server must
# never hold an agent turn forever; callers without an explicit timeout get this.
DEFAULT_MCP_CALL_TIMEOUT = 120.0

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
    # Defaults so `__new__`-constructed test doubles never AttributeError.
    _global_config_ensured = False
    _warned_broken_config_files: set = None  # type: ignore[assignment]

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

    def stop_all(self):
        """Stops all running MCP client processes."""
        for client in list(self.clients.values()):
            stop = getattr(client, "stop", None)
            if not callable(stop):
                continue
            try:
                stop()
            except Exception:
                logger.warning("Failed to stop MCP client", exc_info=True)
        self.clients.clear()

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
        """Lazily materialize the default global config, only once per manager.

        Doing this at construction time wrote `~/.johnston/mcp.json` as a side
        effect of merely instantiating the manager (and polluted test runs with
        real user-config writes); deferring to first use keeps the constructor
        side-effect free while preserving prod behavior.
        """
        try:
            from core.infrastructure.config.config_helpers import ensure_json_config

            ensure_json_config(self.global_file, {"mcpServers": {}})
        except Exception:
            logger.debug("Failed to ensure default global MCP config", exc_info=True)
        self._global_config_ensured = True

    def _warn_broken_config(self, path: str, reason: str = "") -> None:
        """Log a broken-config warning once per (file, reason), not per call."""
        warned = self._warned_broken_config_files
        if warned is None:
            warned = self._warned_broken_config_files = set()
        key = (path, reason)
        if key in warned:
            return
        warned.add(key)
        if reason:
            logger.warning("Failed to load MCP servers config %s: %s", path, reason)
        else:
            logger.warning("Failed to load MCP servers config %s: invalid JSON", path)

    @staticmethod
    def _command_parts_valid(cmd: Any) -> bool:
        """Validate a server command before it reaches subprocess launch.

        Accepts a single string (binary name) or a non-empty list of strings;
        anything else (int, None, mixed types) fails validation so the server is
        skipped with a warning instead of crashing on a later ``list(cmd)``.
        """
        if isinstance(cmd, str):
            return True
        return isinstance(cmd, list) and bool(cmd) and all(isinstance(c, str) for c in cmd)

    def _servers_signature(self) -> Tuple:
        """Returns (path, mtime_ns, size) for both config files to detect changes."""
        sig = []
        for path in (self.global_file, self.project_file):
            try:
                st = os.stat(path)
                sig.append((path, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((path, None, None))
        return tuple(sig)

    def _tools_fetch_stale(self, server_name: str, ttl: float = 5.0) -> bool:
        """True if this server's cached tools list is stale, based on last fetch time."""
        client = self.clients.get(server_name)
        if client is None:
            return False
        return bool(client.is_tools_stale(ttl=ttl))

    def _load_config_file(self, path: str, scope: str, servers: Dict[str, Dict[str, Any]]) -> None:
        """Parse one MCP config file into ``servers``, validating entries.

        Invalid entries (broken command/env/args types) are skipped with a
        one-time warning; a malformed file logs a one-time warning and yields
        nothing rather than spamming WARNING+traceback on every call.
        """
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self._warn_broken_config(path)
            return

        mcp_servers = data.get("mcpServers") or {}
        if not isinstance(mcp_servers, dict):
            self._warn_broken_config(path, reason="'mcpServers' must be an object")
            return

        for k, v in mcp_servers.items():
            if not isinstance(v, dict):
                self._warn_broken_config(path, reason=f"server '{k}': entry must be an object")
                continue
            v_copy = dict(v)
            if not self._command_parts_valid(v_copy.get("command")):
                self._warn_broken_config(path, reason=f"server '{k}': invalid command {v_copy.get('command')!r}")
                continue
            args = v_copy.get("args")
            if args is not None and not isinstance(args, list):
                self._warn_broken_config(path, reason=f"server '{k}': 'args' must be an array")
                args = None
            v_copy["args"] = args or []
            env = v_copy.get("env")
            if env is not None and not isinstance(env, dict):
                self._warn_broken_config(path, reason=f"server '{k}': 'env' must be an object")
                env = None
            v_copy["env"] = env
            cwd = v_copy.get("cwd")
            if cwd is not None and not isinstance(cwd, str):
                self._warn_broken_config(path, reason=f"server '{k}': 'cwd' must be a string")
                cwd = None
            v_copy["cwd"] = cwd
            v_copy["name"] = k
            v_copy["scope"] = scope
            servers[k] = v_copy

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

        file_to_update = (
            self.project_file
            if target["scope"] == "project" and os.path.exists(self.project_file)
            else self.global_file
        )

        try:
            cfg = {"mcpServers": {}}
            if os.path.exists(file_to_update):
                with open(file_to_update, "r", encoding="utf-8") as f:
                    cfg = json.load(f)

            if "mcpServers" not in cfg:
                cfg["mcpServers"] = {}

            if name in cfg["mcpServers"]:
                cfg["mcpServers"][name].update(key_updates)
            else:
                server_dict = {
                    "command": target.get("command"),
                    "args": target.get("args"),
                    "env": target.get("env"),
                    "url": target.get("url"),
                    "disabled": target.get("disabled", False),
                }
                server_dict.update(key_updates)
                cfg["mcpServers"][name] = server_dict

            atomic_write_json(file_to_update, cfg, indent=2)
        except Exception as e:
            logger.warning("Failed to update config for MCP server %s: %s", name, e)

        return target

    async def _update_server_config_async(self, name: str, key_updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Async variant of ``_update_server_config``: the read-modify-write of
        the config file runs on a worker thread so the event loop is not blocked."""
        return await asyncio.to_thread(self._update_server_config, name, key_updates)

    def _format_tool_schema(self, tool: Dict[str, Any], server_name: str, seen_names: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Formats tool dict to OpenAI function format and handles name collisions across servers."""
        t_name = tool.get("name")
        if not t_name:
            return None

        exposed_name = t_name
        if t_name in seen_names and seen_names[t_name] != server_name:
            exposed_name = f"{server_name}__{t_name}"
        else:
            seen_names[t_name] = server_name

        return {
            "type": "function",
            "function": {
                "name": exposed_name,
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
            },
            "_mcp_server": server_name,
            "_mcp_tool_name": t_name,
        }

    def toggle_server(self, name: str) -> bool:
        """
        Toggles disabled state of server by name.
        Saves updated state to the appropriate config file (project or global).
        Returns new enabled state (True = enabled, False = disabled).
        """
        servers = self.load_servers()
        target = next((s for s in servers if s["name"] == name), None)
        if not target:
            return False

        new_disabled = not target.get("disabled", False)
        if self._update_server_config(name, {"disabled": new_disabled}) is None:
            return False

        # Stop client if disabled
        if new_disabled and name in self.clients:
            self.clients[name].stop()
            del self.clients[name]

        return not new_disabled

    def get_active_tools(self) -> List[Dict[str, Any]]:
        """Connects to enabled MCP servers and returns their tools in OpenAI function format."""
        tools: List[Dict[str, Any]] = []
        servers = self.load_servers()
        seen_names: Dict[str, str] = {}  # tool_name -> server_name

        for s in servers:
            if s.get("disabled", False):
                continue

            name = s["name"]
            cmd = s.get("command")
            if not cmd:
                continue

            args = s.get("args") or []
            env = s.get("env")
            cwd = s.get("cwd")
            full_cmd = [cmd] + list(args) if isinstance(cmd, str) else list(cmd) + list(args)

            client = self.clients.get(name)
            if not client:
                client = MCPProcessClient(name, full_cmd, cwd=cwd, env=env)
                if client.start():
                    self.clients[name] = client
                else:
                    continue
            else:
                if self._tools_fetch_stale(name):
                    try:
                        client.fetch_tools()
                    except Exception:
                        logger.warning("Failed to fetch tools for MCP server %s", name, exc_info=True)

            for t in client.tools:
                formatted = self._format_tool_schema(t, name, seen_names)
                if formatted:
                    tools.append(formatted)

        return tools

    async def _load_server_tools_async(self, server: Dict[str, Any], timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Start (or refresh) a single MCP server and return its raw tools.

        Isolated per server with a short deadline so one slow/broken server can
        never block the others: any failure yields an empty list for that server
        only. If a freshly-created client cannot become ready in time it is torn
        down so no orphaned subprocess leaks. Naming/formatting happens later,
        sequentially, so name-collision assignment stays deterministic.
        """
        name = server["name"]
        cmd = server.get("command")
        if not cmd:
            return []

        args = server.get("args") or []
        env = server.get("env")
        cwd = server.get("cwd")
        full_cmd = [cmd] + list(args) if isinstance(cmd, str) else list(cmd) + list(args)

        client = self.clients.get(name)
        created = False
        if client is None:
            client = MCPProcessClient(name, full_cmd, cwd=cwd, env=env)
            created = True

        async def _cleanup_if_created() -> None:
            # A freshly-created client that failed to become ready must be torn
            # down so no orphaned subprocess leaks. Both failure paths (start
            # timeout and start failure) pop the client from the cache before
            # calling this, so the guard reduces to "we created it".
            if not created:
                return
            try:
                await client.stop_async()
            except Exception:
                logger.debug("Failed to stop unready MCP client %s", name, exc_info=True)
            self.clients.pop(name, None)

        try:
            if created:
                try:
                    ok = await asyncio.wait_for(client.start_async(), timeout=timeout)
                except asyncio.TimeoutError:
                    client.last_error = client.last_error or f"Server start timed out after {timeout}s"
                    self.clients.pop(name, None)
                    await _cleanup_if_created()
                    return []
                except Exception as exc:
                    if not client.last_error:
                        client.last_error = str(exc)
                    self.clients.pop(name, None)
                    await _cleanup_if_created()
                    return []
                if not ok:
                    if not client.last_error:
                        client.last_error = "Failed to start"
                    self.clients.pop(name, None)
                    await _cleanup_if_created()
                    return []
                self.clients[name] = client
            elif self._tools_fetch_stale(name):
                try:
                    await asyncio.wait_for(client.fetch_tools_async(), timeout=timeout)
                except Exception:
                    logger.warning("Failed to fetch tools asynchronously for MCP server %s", name, exc_info=True)

            return list(client.tools)
        except Exception:
            logger.warning("MCP server %s failed to load tools", name, exc_info=True)
            return []

    async def get_active_tools_async(self) -> List[Dict[str, Any]]:
        servers = await self.load_servers_async()

        eligible = [s for s in servers if not s.get("disabled", False) and s.get("command")]
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
            if server.get("disabled", False):
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

        if task is not None and (now - self._tools_refresh_time) < max_age:
            # Most recent warmup finished within the freshness window.
            return self.get_cached_tools()

        task = asyncio.create_task(self.get_active_tools_async())
        self._tools_refresh_task = task

        def _on_done(done: asyncio.Task) -> None:
            self._tools_refresh_time = time.monotonic()
            if self._tools_refresh_task is done:
                self._tools_refresh_task = None

        task.add_done_callback(_on_done)

        return self.get_cached_tools()

    def is_loading(self) -> bool:
        """True if background MCP server initialization or tool loading is currently in progress."""
        return self._tools_refresh_task is not None and not self._tools_refresh_task.done()

    def get_tool_capabilities(self, server_name: str, tool_name: str) -> List[str]:
        """Returns configured capabilities for an MCP tool.

        Unknown MCP tools intentionally return an empty list; policy treats that
        as blocked until the project/global MCP config classifies the tool.
        """
        for server in self.load_servers():
            if server.get("name") != server_name:
                continue
            caps_cfg = server.get("capabilities") or {}
            caps = caps_cfg.get(tool_name)
            if caps is None:
                caps = caps_cfg.get(f"{server_name}__{tool_name}")
            if isinstance(caps, str):
                return [caps]
            if isinstance(caps, list):
                return [str(c) for c in caps if str(c).strip()]
            return []
        return []

    def get_capabilities_for_exposed_tool(self, exposed_name: str) -> List[str]:
        if "__" in exposed_name:
            server_name, tool_name = exposed_name.split("__", 1)
            return self.get_tool_capabilities(server_name, tool_name)

        matches: List[str] = []
        for server in self.load_servers():
            server_name = server.get("name", "")
            caps = self.get_tool_capabilities(server_name, exposed_name)
            if caps:
                matches.extend(caps)
        return sorted(set(matches))

    def _resolve_target_client_and_tool(
        self, tool_name: str, active_tools: List[Dict[str, Any]], target_server: Optional[str] = None
    ) -> Tuple[Optional[MCPProcessClient], Optional[str]]:
        """Helper to match exposed/raw tool_name against active MCP clients.

        Exact match on the exposed or raw name runs FIRST, so a tool whose real
        name contains ``__`` (e.g. ``db__query``) still resolves; the
        ``server__tool`` namespace split is only attempted for legacy names that
        no exact match covered.
        """
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

        if not target_server and "__" in tool_name:
            req_server, req_tool = tool_name.split("__", 1)
            for t in active_tools:
                s_name = t.get("_mcp_server")
                o_name = t.get("_mcp_tool_name")
                if s_name == req_server and o_name == req_tool:
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
        """
        Executes an MCP tool call by name across active MCP clients.
        Supports both direct tool_name, namespaced server_name__tool_name, or explicit target_server.
        """
        active_tools = self.get_active_tools()
        client, o_name = self._resolve_target_client_and_tool(tool_name, active_tools, target_server=target_server)
        if client and o_name:
            return client.call_tool(
                o_name, arguments, timeout=timeout if timeout is not None else DEFAULT_MCP_CALL_TIMEOUT
            )
        return None

    async def call_tool_async(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        target_server: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        active_tools = await self.get_active_tools_async()
        client, o_name = self._resolve_target_client_and_tool(tool_name, active_tools, target_server=target_server)
        if client and o_name:
            return await client.call_tool_async(
                o_name, arguments, timeout=timeout if timeout is not None else DEFAULT_MCP_CALL_TIMEOUT
            )
        return None

    def get_system_prompt_snippet(self) -> str:
        """Returns a prompt snippet listing enabled MCP tools grouped by server.

        Kept minimal: full tool schemas (names, descriptions, parameters) are
        already provided to the model via the function-call declaration. This
        snippet only carries the server->tools grouping that the schema lacks.
        """
        cached_tools = self.get_cached_tools()
        if not cached_tools:
            return ""

        by_server: Dict[str, List[str]] = {}
        for t in cached_tools:
            fn = t.get("function", {})
            server = t.get("_mcp_server", "")
            name = fn.get("name")
            if not name:
                continue
            by_server.setdefault(server, []).append(name)

        lines = ["## MCP Tools"]
        for server in sorted(by_server):
            names = ", ".join(sorted(by_server[server]))
            lines.append(f"- {server}: {names}")

        return "\n".join(lines)
