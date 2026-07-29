"""
MCP (Model Context Protocol) Manager for Johnston.
Handles global (~/.johnston/mcp.json) and project (.johnston/mcp.json) MCP servers.
Supports stdio process execution with JSON-RPC 2.0.
"""
import atexit
import json
import os
import select
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

from core.config import CONFIG_DIR

GLOBAL_MCP_FILE = os.path.join(CONFIG_DIR, "mcp.json")
PROJECT_MCP_FILE = os.path.join(".johnston", "mcp.json")

class MCPProcessClient:
    """Stdio JSON-RPC 2.0 client for MCP servers"""

    def __init__(self, name: str, command: str | List[str], cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None):
        self.name = name
        if isinstance(command, str):
            self.cmd = [command]
        else:
            self.cmd = list(command)
        self.cwd = cwd
        self.env = env
        self.process: Optional[subprocess.Popen] = None
        self.req_id = 0
        self.tools: List[Dict[str, Any]] = []
        self._stopped = False
        self._buffer = ""
        self._lock = threading.RLock()
        self._pending_responses: Dict[int, Dict[str, Any]] = {}

    def start(self) -> bool:
        self._stopped = False
        if self.process and self.process.poll() is None:
            return True

        run_env = os.environ.copy()
        if self.env:
            run_env.update(self.env)

        try:
            self.process = subprocess.Popen(
                self.cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd or os.getcwd(),
                env=run_env,
                text=True,
                bufsize=1
            )
            if self.process.stdout:
                try:
                    os.set_blocking(self.process.stdout.fileno(), False)
                except Exception:
                    pass
            self._buffer = ""
            return self._initialize()
        except Exception as e:
            print(f"Failed to start MCP server {self.name}: {e}")
            return False

    def stop(self):
        self._stopped = True
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                if self.process.stdout:
                    self.process.stdout.close()
                if self.process.stderr:
                    self.process.stderr.close()
            except Exception:
                pass

            try:
                self.process.terminate()
                self.process.wait(timeout=1)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def _send(self, message: Dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            return
        line = json.dumps(message, ensure_ascii=False) + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()

    def _read_response(self, req_id: Optional[int] = None, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        if not self.process or not self.process.stdout or self._stopped:
            return None

        if req_id is not None and req_id in self._pending_responses:
            return self._pending_responses.pop(req_id)

        start_time = time.time()
        while not self._stopped:
            if req_id is not None and req_id in self._pending_responses:
                return self._pending_responses.pop(req_id)

            while "\n" in self._buffer:
                line_str, self._buffer = self._buffer.split("\n", 1)
                line_str = line_str.strip()
                if not line_str.startswith("{"):
                    continue
                try:
                    data = json.loads(line_str)
                    # Ignore notifications without an id (e.g. notifications/tools/list_changed)
                    if "method" in data and "id" not in data:
                        continue

                    res_id = data.get("id")
                    if req_id is not None and res_id != req_id:
                        if res_id is not None:
                            self._pending_responses[res_id] = data
                        continue

                    return data
                except Exception:
                    continue

            wait_time = 1.0
            if timeout is not None:
                elapsed = time.time() - start_time
                remaining = timeout - elapsed
                if remaining <= 0:
                    return None
                wait_time = min(1.0, max(0.05, remaining))

            try:
                rlist, _, _ = select.select([self.process.stdout], [], [], wait_time)
            except Exception:
                return None

            if self._stopped:
                return None

            if not rlist:
                continue  # Tick completed, check self._stopped again

            try:
                raw_chunk = os.read(self.process.stdout.fileno(), 8192)
                if not raw_chunk:
                    return None
                self._buffer += raw_chunk.decode("utf-8", errors="replace")
            except (OSError, BlockingIOError):
                continue
            except Exception:
                return None

        return None

    def _initialize(self) -> bool:
        self.req_id += 1
        init_req = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "johnston", "version": "1.0.0"}
            }
        }
        self._send(init_req)
        res = self._read_response(req_id=self.req_id, timeout=20.0)
        if not res or "error" in res:
            return False

        # Notify initialized
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.fetch_tools()
        return True

    def fetch_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            self.req_id += 1
            current_id = self.req_id
            req = {
                "jsonrpc": "2.0",
                "id": current_id,
                "method": "tools/list"
            }
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=15.0)
            if res and "result" in res:
                self.tools = res["result"].get("tools", [])
            return self.tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: Optional[float] = None) -> str:
        with self._lock:
            if not self.process or self.process.poll() is not None:
                if not self.start():
                    return f"Error: MCP server '{self.name}' process is not running"

            self.req_id += 1
            current_id = self.req_id
            req = {
                "jsonrpc": "2.0",
                "id": current_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=timeout)
            if not res:
                return f"Error: No response from MCP server '{self.name}'"
            if "error" in res:
                return f"MCP Error: {res['error'].get('message', res['error'])}"

            result = res.get("result", {})
            content_items = result.get("content", [])
            output_parts = []
            for item in content_items:
                if item.get("type") == "text":
                    output_parts.append(item.get("text", ""))
                else:
                    output_parts.append(json.dumps(item, ensure_ascii=False))

            try:
                self.fetch_tools()
            except Exception:
                pass

            output_text = "\n".join(output_parts).strip()
            if output_text:
                return output_text

            return f"MCP tool '{tool_name}' from server '{self.name}' executed successfully."


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
            with open(self.global_file, "w", encoding="utf-8") as f:
                json.dump({"mcpServers": {}}, f, indent=2)

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
                        v_copy["mode"] = v.get("mode") or ("lazy" if v.get("lazy") is True else "eager")
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
                        v_copy["mode"] = v.get("mode") or ("lazy" if v.get("lazy") is True else "eager")
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

            with open(file_to_update, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
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

            with open(file_to_update, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
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
                client = MCPProcessClient(name, full_cmd, cwd=cwd, env=env)
                if client.start():
                    self.clients[name] = client
                else:
                    continue

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
        eager_tools = self.get_active_tools(mode="eager")
        lazy_tools = self.get_active_tools(mode="lazy")

        if not eager_tools and not lazy_tools:
            return ""

        sections = []

        if lazy_tools:
            lazy_by_server: Dict[str, List[Dict[str, Any]]] = {}
            for t in lazy_tools:
                s_name = t["_mcp_server"]
                lazy_by_server.setdefault(s_name, []).append(t)

            lazy_lines = [
                "<mcp_servers>",
                "The following MCP servers are loaded lazily. Use `call_mcp_tool` (server, tool, arguments) to execute."
            ]
            for s_name, t_list in lazy_by_server.items():
                lazy_lines.append(f"\n# {s_name} (Lazy)")
                for t in t_list:
                    fn = t.get("function", {})
                    desc = fn.get("description", "")
                    desc_str = f" — {desc}" if desc else ""
                    lazy_lines.append(f"- {fn.get('name')}{desc_str}")
            lazy_lines.append("</mcp_servers>")
            sections.append("\n".join(lazy_lines))

        if eager_tools:
            eager_lines = ["Available Eager MCP tools in system context:"]
            for t in eager_tools:
                fn = t.get("function", {})
                desc = fn.get("description", "")
                desc_str = f" — {desc}" if desc else ""
                eager_lines.append(f"- {fn.get('name')} (from {t.get('_mcp_server')}){desc_str}")
            sections.append("\n".join(eager_lines))

        return "\n\n".join(sections)
