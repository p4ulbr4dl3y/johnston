"""
MCP (Model Context Protocol) Manager for Johnston.
Handles global (~/.johnston/mcp.json) and project (.johnston/mcp.json) MCP servers.
"""
import asyncio
import atexit
import json
import os
import time
from typing import Any, Dict, List, Optional

from core.config import CONFIG_DIR
from core.mcp_manager.process_client import MCPProcessClient

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
    return _mcp_manager_instance

class MCPManager:
    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_file = GLOBAL_MCP_FILE
        self.project_file = os.path.join(self.project_dir, PROJECT_MCP_FILE)
        self.clients: Dict[str, MCPProcessClient] = {}
        self._tools_refresh_time = 0.0
        self._tools_refresh_task: Optional[asyncio.Task] = None
        self.ensure_default_configs()
        atexit.register(self.stop_all)

    def stop_all(self):
        """Stops all running MCP client processes."""
        for client in list(self.clients.values()):
            try:
                client.stop()
            except Exception:
                pass
        self.clients.clear()

    def ensure_default_configs(self):
        os.makedirs(os.path.dirname(self.global_file), exist_ok=True)
        if not os.path.exists(self.global_file):
            from tools.base import atomic_write_json
            atomic_write_json(self.global_file, {"mcpServers": {}}, indent=2)

    def load_servers(self) -> List[Dict[str, Any]]:
        """
        Loads global and project MCP servers.
        Project servers override global servers with the same key.
        """
        curr_proj_dir = os.path.realpath(self.project_dir or os.getcwd())
        self.project_file = os.path.join(curr_proj_dir, PROJECT_MCP_FILE)
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
                        v_copy["mode"] = v.get("mode", "eager")
                        servers[k] = v_copy
            except Exception:
                pass

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
                        v_copy["mode"] = v.get("mode", "eager")
                        servers[k] = v_copy
            except Exception:
                pass

        return list(servers.values())

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
        target["disabled"] = new_disabled

        file_to_update = self.project_file if target["scope"] == "project" and os.path.exists(self.project_file) else self.global_file

        try:
            cfg = {"mcpServers": {}}
            if os.path.exists(file_to_update):
                with open(file_to_update, "r", encoding="utf-8") as f:
                    cfg = json.load(f)

            if "mcpServers" not in cfg:
                cfg["mcpServers"] = {}

            if name in cfg["mcpServers"]:
                cfg["mcpServers"][name]["disabled"] = new_disabled
            else:
                cfg["mcpServers"][name] = {
                    "command": target.get("command"),
                    "args": target.get("args"),
                    "env": target.get("env"),
                    "url": target.get("url"),
                    "mode": target.get("mode", "eager"),
                    "disabled": new_disabled
                }

            from tools.base import atomic_write_json
            atomic_write_json(file_to_update, cfg, indent=2)
        except Exception as e:
            print(f"Failed to toggle MCP server {name}: {e}")

        # Stop client if disabled
        if new_disabled and name in self.clients:
            self.clients[name].stop()
            del self.clients[name]

        return not new_disabled

    def toggle_mode(self, name: str) -> str:
        """
        Toggles mode between 'eager' and 'lazy' for server by name.
        Saves updated mode to appropriate config file.
        Returns new mode string ('eager' or 'lazy').
        """
        servers = self.load_servers()
        target = next((s for s in servers if s["name"] == name), None)
        if not target:
            return "eager"

        curr_mode = target.get("mode", "eager")
        new_mode = "lazy" if curr_mode == "eager" else "eager"

        file_to_update = self.project_file if target["scope"] == "project" and os.path.exists(self.project_file) else self.global_file

        try:
            cfg = {"mcpServers": {}}
            if os.path.exists(file_to_update):
                with open(file_to_update, "r", encoding="utf-8") as f:
                    cfg = json.load(f)

            if "mcpServers" not in cfg:
                cfg["mcpServers"] = {}

            if name in cfg["mcpServers"]:
                cfg["mcpServers"][name]["mode"] = new_mode
            else:
                cfg["mcpServers"][name] = {
                    "command": target.get("command"),
                    "args": target.get("args"),
                    "env": target.get("env"),
                    "url": target.get("url"),
                    "mode": new_mode,
                    "disabled": target.get("disabled", False)
                }

            from tools.base import atomic_write_json
            atomic_write_json(file_to_update, cfg, indent=2)
        except Exception as e:
            print(f"Failed to toggle mode for MCP server {name}: {e}")

        return new_mode

    def get_active_tools(self, mode: Optional[str] = "eager") -> List[Dict[str, Any]]:
        """
        Connects to enabled MCP servers and returns their tools in OpenAI function format.
        mode can be "eager" (default), "lazy", or "all" (or None for all).
        """
        tools: List[Dict[str, Any]] = []
        servers = self.load_servers()
        seen_names: Dict[str, str] = {}  # tool_name -> server_name

        for s in servers:
            if s.get("disabled", False):
                continue

            s_mode = s.get("mode", "eager")
            if mode and mode != "all" and s_mode != mode:
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
                if s_mode == "lazy" and mode not in ("lazy", "all"):
                    continue
                client = MCPProcessClient(name, full_cmd, cwd=cwd, env=env)
                if client.start():
                    self.clients[name] = client
                else:
                    continue
            else:
                if s_mode == "lazy" and mode not in ("lazy", "all"):
                    continue
                try:
                    client.fetch_tools()
                except Exception:
                    pass

            for t in client.tools:
                t_name = t.get("name")
                if not t_name:
                    continue

                exposed_name = t_name
                if t_name in seen_names and seen_names[t_name] != name:
                    exposed_name = f"{name}__{t_name}"
                else:
                    seen_names[t_name] = name

                tools.append({
                    "type": "function",
                    "function": {
                        "name": exposed_name,
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {"type": "object", "properties": {}})
                    },
                    "_mcp_server": name,
                    "_mcp_tool_name": t_name,
                    "_mcp_mode": s_mode
                })

        return tools

    async def get_active_tools_async(self, mode: Optional[str] = "eager") -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []
        servers = self.load_servers()
        seen_names: Dict[str, str] = {}

        for s in servers:
            if s.get("disabled", False):
                continue

            s_mode = s.get("mode", "eager")
            if mode and mode != "all" and s_mode != mode:
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
                if s_mode == "lazy" and mode not in ("lazy", "all"):
                    continue
                client = MCPProcessClient(name, full_cmd, cwd=cwd, env=env)
                if await client.start_async():
                    self.clients[name] = client
                else:
                    continue
            else:
                if s_mode == "lazy" and mode not in ("lazy", "all"):
                    continue
                try:
                    await client.fetch_tools_async()
                except Exception:
                    pass

            for t in client.tools:
                t_name = t.get("name")
                if not t_name:
                    continue

                exposed_name = t_name
                if t_name in seen_names and seen_names[t_name] != name:
                    exposed_name = f"{name}__{t_name}"
                else:
                    seen_names[t_name] = name

                tools.append({
                    "type": "function",
                    "function": {
                        "name": exposed_name,
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {"type": "object", "properties": {}})
                    },
                    "_mcp_server": name,
                    "_mcp_tool_name": t_name,
                    "_mcp_mode": s_mode
                })

        return tools

    def get_cached_tools(self, mode: Optional[str] = "eager") -> List[Dict[str, Any]]:
        """Return already discovered tools without starting processes or performing I/O."""
        tools: List[Dict[str, Any]] = []
        seen_names: Dict[str, str] = {}

        for server in self.load_servers():
            if server.get("disabled", False):
                continue
            server_mode = server.get("mode", "eager")
            if mode and mode != "all" and server_mode != mode:
                continue

            server_name = server.get("name", "")
            client = self.clients.get(server_name)
            if client is None:
                continue

            for tool in client.tools:
                tool_name = tool.get("name")
                if not tool_name:
                    continue
                exposed_name = tool_name
                if tool_name in seen_names and seen_names[tool_name] != server_name:
                    exposed_name = f"{server_name}__{tool_name}"
                else:
                    seen_names[tool_name] = server_name

                tools.append({
                    "type": "function",
                    "function": {
                        "name": exposed_name,
                        "description": tool.get("description", ""),
                        "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                    },
                    "_mcp_server": server_name,
                    "_mcp_tool_name": tool_name,
                    "_mcp_mode": server_mode,
                })

        return tools

    async def ensure_tools_ready_async(self, max_age: float = 30.0) -> List[Dict[str, Any]]:
        """Refresh MCP schemas asynchronously, coalescing concurrent callers."""
        now = time.monotonic()
        if now - self._tools_refresh_time < max_age:
            return self.get_cached_tools(mode="all")

        task = self._tools_refresh_task
        if task is None or task.done():
            # Only warm up eager servers here. Lazy servers stay unstarted
            # until an explicit call_mcp; auto-starting them spawns subprocess
            # reader threads that block interpreter shutdown in headless mode.
            task = asyncio.create_task(self.get_active_tools_async(mode="eager"))
            self._tools_refresh_task = task

        try:
            tools = await task
            self._tools_refresh_time = time.monotonic()
            return tools
        finally:
            if self._tools_refresh_task is task and task.done():
                self._tools_refresh_task = None

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

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], target_server: Optional[str] = None, timeout: Optional[float] = None) -> Optional[str]:
        """
        Executes an MCP tool call by name across active MCP clients.
        Supports both direct tool_name, namespaced server_name__tool_name, or explicit target_server.
        """
        req_server = target_server
        req_tool = tool_name

        if "__" in tool_name and not req_server:
            req_server, req_tool = tool_name.split("__", 1)

        active_tools = self.get_active_tools(mode="all")
        for t in active_tools:
            fn = t.get("function", {})
            s_name = t.get("_mcp_server")
            o_name = t.get("_mcp_tool_name")
            exposed_name = fn.get("name")

            if req_server:
                if s_name == req_server and (o_name == req_tool or exposed_name == tool_name):
                    client = self.clients.get(s_name)
                    if client:
                        return client.call_tool(o_name, arguments, timeout=timeout)
            else:
                if exposed_name == tool_name or o_name == tool_name:
                    client = self.clients.get(s_name)
                    if client:
                        return client.call_tool(o_name, arguments, timeout=timeout)
        return None

    async def call_tool_async(self, tool_name: str, arguments: Dict[str, Any], target_server: Optional[str] = None, timeout: Optional[float] = None) -> Optional[str]:
        req_server = target_server
        req_tool = tool_name

        if "__" in tool_name and not req_server:
            req_server, req_tool = tool_name.split("__", 1)

        active_tools = await self.get_active_tools_async(mode="all")
        for t in active_tools:
            fn = t.get("function", {})
            s_name = t.get("_mcp_server")
            o_name = t.get("_mcp_tool_name")
            exposed_name = fn.get("name")

            if req_server:
                if s_name == req_server and (o_name == req_tool or exposed_name == tool_name):
                    client = self.clients.get(s_name)
                    if client:
                        return await client.call_tool_async(o_name, arguments, timeout=timeout)
            else:
                if exposed_name == tool_name or o_name == tool_name:
                    client = self.clients.get(s_name)
                    if client:
                        return await client.call_tool_async(o_name, arguments, timeout=timeout)
        return None

    def get_tool_schema(self, server_name: str, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Returns the raw parameters inputSchema dict for a specific tool on an MCP server.
        """
        active_tools = self.get_active_tools(mode="all")
        for t in active_tools:
            s_name = t.get("_mcp_server")
            o_name = t.get("_mcp_tool_name")
            fn = t.get("function", {})
            exposed_name = fn.get("name")

            if s_name == server_name and (o_name == tool_name or exposed_name == tool_name):
                return fn.get("parameters")
        return None

    def get_system_prompt_snippet(self) -> str:
        """
        Returns a prompt snippet summarizing currently enabled MCP servers.
        Formats lazy MCP servers under <mcp_servers> block and eager tools if present.
        """
        eager_tools = self.get_cached_tools(mode="eager")
        lazy_tools = self.get_cached_tools(mode="lazy")

        if not eager_tools and not lazy_tools:
            return ""

        sections = []

        if lazy_tools:
            lazy_by_server: Dict[str, List[Dict[str, Any]]] = {}
            for t in lazy_tools:
                s_name = t["_mcp_server"]
                lazy_by_server.setdefault(s_name, []).append(t)

            lazy_lines = [
                "## MCP Servers",
                "The following MCP servers are loaded lazily. Use `call_mcp` (server, tool, arguments) to execute."
            ]
            for s_name, t_list in lazy_by_server.items():
                lazy_lines.append(f"\n### {s_name} (Lazy)")
                for t in t_list:
                    fn = t.get("function", {})
                    name = fn.get("name", "")
                    desc = fn.get("description", "")
                    desc_str = f" — {desc}" if desc else ""
                    params = fn.get("parameters", {}).get("properties", {})
                    param_names = ", ".join(params.keys()) if params else ""
                    sig = f"{name}({param_names})" if param_names else name
                    lazy_lines.append(f"- {sig}{desc_str}")
            sections.append("\n".join(lazy_lines))

        if eager_tools:
            eager_lines = [
                "## Eager MCP Tools",
                "Available Eager MCP tools in system context:"
            ]
            for t in eager_tools:
                fn = t.get("function", {})
                desc = fn.get("description", "")
                desc_str = f" — {desc}" if desc else ""
                eager_lines.append(f"- {fn.get('name')} (from {t.get('_mcp_server')}){desc_str}")
            sections.append("\n".join(eager_lines))

        return "\n\n".join(sections)
