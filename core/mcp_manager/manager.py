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

from core.config import CONFIG_DIR
from core.mcp_manager.process_client import MCPProcessClient

logger = logging.getLogger(__name__)

GLOBAL_MCP_FILE = os.path.join(CONFIG_DIR, "mcp.json")
PROJECT_MCP_FILE = os.path.join(".johnston", "mcp.json")


_mcp_manager_instance: Optional["MCPManager"] = None


def get_mcp_manager(project_dir: Optional[str] = None) -> "MCPManager":
    global _mcp_manager_instance
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
    return _mcp_manager_instance


class MCPManager:
    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_file = GLOBAL_MCP_FILE
        self.project_file = os.path.join(self.project_dir, PROJECT_MCP_FILE)
        self.clients: Dict[str, MCPProcessClient] = {}
        self._tools_refresh_time = 0.0
        self._tools_refresh_task: Optional[asyncio.Task] = None
        self._servers_cache_signature: Optional[Tuple] = None
        self._servers_cache: List[Dict[str, Any]] = []
        self._tools_fetch_time: Dict[str, float] = {}  # server name -> last fetch_tools monotonic time
        self.ensure_default_configs()
        atexit.register(self.stop_all)

    def stop_all(self):
        """Stops all running MCP client processes."""
        for client in list(self.clients.values()):
            try:
                client.stop()
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
        for client in list(self.clients.values()):
            try:
                client.stop()
            except Exception:
                logger.warning("Failed to stop MCP client on project switch", exc_info=True)
        self.clients.clear()
        self._servers_cache_signature = None
        self._servers_cache = []
        self._tools_fetch_time.clear()

    def ensure_default_configs(self):
        from core.config_helpers import ensure_json_config

        ensure_json_config(self.global_file, {"mcpServers": {}})

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
        last = self._tools_fetch_time.get(server_name)
        if last is None:
            return True
        return (time.monotonic() - last) >= ttl

    def load_servers(self) -> List[Dict[str, Any]]:
        """
        Loads global and project MCP servers.
        Project servers override global servers with the same key.

        Results are cached by config file mtime/size so repeated calls (e.g. per
        tool call) do not re-read and re-parse JSON on every invocation. Cache is
        invalidated automatically when either config file changes, preserving
        hot-reload.
        """
        curr_proj_dir = os.path.realpath(self.project_dir or os.getcwd())
        self.project_file = os.path.join(curr_proj_dir, PROJECT_MCP_FILE)
        signature = self._servers_signature()
        if signature == self._servers_cache_signature:
            return list(self._servers_cache)

        servers: Dict[str, Dict[str, Any]] = {}

        # 1. Load global
        if os.path.exists(self.global_file):
            try:
                with open(self.global_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.get("mcpServers", {}).items():
                        v_copy = dict(v)
                        v_copy["name"] = k
                        v_copy["scope"] = "global"
                        servers[k] = v_copy
            except Exception:
                logger.warning("Failed to load global MCP servers config", exc_info=True)

        # 2. Load project (only if distinct from global_file)
        real_global = os.path.realpath(self.global_file)
        real_project = os.path.realpath(self.project_file)
        if os.path.exists(self.project_file) and real_project != real_global:
            try:
                with open(self.project_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.get("mcpServers", {}).items():
                        v_copy = dict(v)
                        v_copy["name"] = k
                        v_copy["scope"] = "project"
                        servers[k] = v_copy
            except Exception:
                logger.warning("Failed to load project MCP servers config", exc_info=True)

        self._servers_cache = list(servers.values())
        self._servers_cache_signature = signature
        return list(self._servers_cache)

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

            from core.platform_utils import atomic_write_json

            atomic_write_json(file_to_update, cfg, indent=2)
        except Exception as e:
            logger.warning("Failed to update config for MCP server %s: %s", name, e)

        return target

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
            args = s.get("args") or []
            env = s.get("env")
            cwd = s.get("cwd")

            if not cmd:
                continue

            full_cmd = [cmd] + args if isinstance(cmd, str) else list(cmd) + args

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
                        self._tools_fetch_time[name] = time.monotonic()
                    except Exception:
                        logger.warning("Failed to fetch tools for MCP server %s", name, exc_info=True)

            for t in client.tools:
                formatted = self._format_tool_schema(t, name, seen_names)
                if formatted:
                    tools.append(formatted)

        return tools

    async def _load_server_tools_async(
        self, server: Dict[str, Any], seen_names: Dict[str, str], timeout: float = 15.0
    ) -> List[Dict[str, Any]]:
        """Start (or refresh) a single MCP server and return its formatted tools.

        Isolated per server with a short deadline so one slow/broken server can
        never block the others: any failure yields an empty list for that server
        only. If a freshly-created client cannot become ready in time it is torn
        down so no orphaned subprocess leaks.
        """
        name = server["name"]
        cmd = server.get("command")
        if not cmd:
            return []

        args = server.get("args") or []
        env = server.get("env")
        cwd = server.get("cwd")
        full_cmd = [cmd] + args if isinstance(cmd, str) else list(cmd) + args

        client = self.clients.get(name)
        created = False
        if client is None:
            client = MCPProcessClient(name, full_cmd, cwd=cwd, env=env)
            created = True

        def _cleanup_if_created() -> None:
            if created and self.clients.get(name) is not client:
                try:
                    client.stop()
                except Exception:
                    logger.debug("Failed to stop unready MCP client %s", name, exc_info=True)

        try:
            if created:
                try:
                    ok = await asyncio.wait_for(client.start_async(), timeout=timeout)
                except (asyncio.TimeoutError, Exception) as exc:
                    client.last_error = str(exc)
                    self.clients[name] = client
                    _cleanup_if_created()
                    return []
                if not ok:
                    if not getattr(client, "last_error", None):
                        client.last_error = "Failed to start"
                    self.clients[name] = client
                    _cleanup_if_created()
                    return []
                self.clients[name] = client
            elif self._tools_fetch_stale(name):
                try:
                    await asyncio.wait_for(client.fetch_tools_async(), timeout=timeout)
                    self._tools_fetch_time[name] = time.monotonic()
                except (asyncio.TimeoutError, Exception):
                    logger.warning("Failed to fetch tools asynchronously for MCP server %s", name, exc_info=True)

            tools = []
            for t in client.tools:
                formatted = self._format_tool_schema(t, name, seen_names)
                if formatted:
                    tools.append(formatted)
            return tools
        except Exception:
            logger.warning("MCP server %s failed to load tools", name, exc_info=True)
            return []

    async def get_active_tools_async(self) -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []
        servers = self.load_servers()
        seen_names: Dict[str, str] = {}

        eligible = [s for s in servers if not s.get("disabled", False) and s.get("command")]
        # Start every server concurrently with an isolated per-server deadline so
        # a slow/cold (npx/uvx) or broken server cannot stall the others.
        results = await asyncio.gather(*(self._load_server_tools_async(s, seen_names) for s in eligible))
        for server_tools in results:
            tools.extend(server_tools)

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
        """
        now = time.monotonic()
        task = self._tools_refresh_task

        if task is not None and not task.done() and (now - self._tools_refresh_time) < max_age:
            # A warmup is already in flight and its results are still fresh:
            # return what we have; the build_x caller snapshots cached tools.
            return self.get_cached_tools()

        if task is None or task.done():
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
        """Helper to match exposed/raw tool_name against active MCP clients."""
        req_server = target_server
        req_tool = tool_name

        if "__" in tool_name and not req_server:
            req_server, req_tool = tool_name.split("__", 1)

        for t in active_tools:
            fn = t.get("function", {})
            s_name = t.get("_mcp_server")
            o_name = t.get("_mcp_tool_name")
            exposed_name = fn.get("name")

            if req_server:
                if s_name == req_server and (o_name == req_tool or exposed_name == tool_name):
                    client = self.clients.get(s_name)
                    if client:
                        return client, o_name
            else:
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
        """
        Executes an MCP tool call by name across active MCP clients.
        Supports both direct tool_name, namespaced server_name__tool_name, or explicit target_server.
        """
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
        active_tools = await self.get_active_tools_async()
        client, o_name = self._resolve_target_client_and_tool(tool_name, active_tools, target_server=target_server)
        if client and o_name:
            return await client.call_tool_async(o_name, arguments, timeout=timeout)
        return None

    def get_tool_schema(self, server_name: str, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Returns the raw parameters inputSchema dict for a specific tool on an MCP server.
        """
        active_tools = self.get_active_tools()
        for t in active_tools:
            s_name = t.get("_mcp_server")
            o_name = t.get("_mcp_tool_name")
            fn = t.get("function", {})
            exposed_name = fn.get("name")

            if s_name == server_name and (o_name == tool_name or exposed_name == tool_name):
                return fn.get("parameters")
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
