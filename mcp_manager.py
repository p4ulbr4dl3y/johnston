"""
MCP (Model Context Protocol) Manager for TUI.
Handles global (~/.tui/mcp.json) and project (.tui/mcp.json) MCP servers.
Supports stdio process execution with JSON-RPC 2.0.
"""
import os
import json
import asyncio
import subprocess
from typing import Dict, List, Any, Optional
from config import CONFIG_DIR

GLOBAL_MCP_FILE = os.path.join(CONFIG_DIR, "mcp.json")
PROJECT_MCP_FILE = os.path.join(".tui", "mcp.json")

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

    def start(self) -> bool:
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
            return self._initialize()
        except Exception as e:
            print(f"Failed to start MCP server {self.name}: {e}")
            return False

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
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

    def _read_response(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        if not self.process or not self.process.stdout:
            return None
        
        while True:
            line = self.process.stdout.readline()
            if not line:
                return None
            line_str = line.strip()
            if not line_str.startswith("{"):
                continue
            try:
                return json.loads(line_str)
            except Exception:
                continue

    def _initialize(self) -> bool:
        self.req_id += 1
        init_req = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "tui", "version": "1.0.0"}
            }
        }
        self._send(init_req)
        res = self._read_response(timeout=5.0)
        if not res or "error" in res:
            return False

        # Notify initialized
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.fetch_tools()
        return True

    def fetch_tools(self) -> List[Dict[str, Any]]:
        self.req_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": "tools/list"
        }
        self._send(req)
        res = self._read_response(timeout=5.0)
        if res and "result" in res:
            self.tools = res["result"].get("tools", [])
        return self.tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        if not self.process or self.process.poll() is not None:
            if not self.start():
                return f"Error: MCP server '{self.name}' process is not running"

        self.req_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        self._send(req)
        res = self._read_response(timeout=30.0)
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

        return "\n".join(output_parts) or "Success (empty response)"


_mcp_manager_instance: Optional["MCPManager"] = None

def get_mcp_manager(project_dir: Optional[str] = None) -> "MCPManager":
    global _mcp_manager_instance
    if _mcp_manager_instance is None:
        _mcp_manager_instance = MCPManager(project_dir=project_dir)
    return _mcp_manager_instance

class MCPManager:
    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_file = GLOBAL_MCP_FILE
        self.project_file = os.path.join(self.project_dir, PROJECT_MCP_FILE)
        self.clients: Dict[str, MCPProcessClient] = {}
        self.ensure_default_configs()

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
        servers: Dict[str, Dict[str, Any]] = {}

        # 1. Load global
        if os.path.exists(self.global_file):
            try:
                with open(self.global_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.get("mcpServers", {}).items():
                        v["name"] = k
                        v["scope"] = "global"
                        servers[k] = v
            except Exception:
                pass

        # 2. Load project
        if os.path.exists(self.project_file):
            try:
                with open(self.project_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.get("mcpServers", {}).items():
                        v["name"] = k
                        v["scope"] = "project"
                        servers[k] = v
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

    def get_active_tools(self) -> List[Dict[str, Any]]:
        """
        Connects to all enabled MCP servers and returns their tools in OpenAI function format.
        """
        tools: List[Dict[str, Any]] = []
        servers = self.load_servers()

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

            for t in client.tools:
                t_name = t.get("name")
                if not t_name:
                    continue

                tools.append({
                    "type": "function",
                    "function": {
                        "name": t_name,
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {"type": "object", "properties": {}})
                    },
                    "_mcp_server": name,
                    "_mcp_tool_name": t_name
                })

        return tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """
        Executes an MCP tool call by name across active MCP clients.
        """
        active_tools = self.get_active_tools()
        for t in active_tools:
            fn = t.get("function", {})
            if fn.get("name") == tool_name:
                server_name = t.get("_mcp_server")
                orig_tool_name = t.get("_mcp_tool_name")
                client = self.clients.get(server_name)
                if client:
                    return client.call_tool(orig_tool_name, arguments)
        return None

    def get_system_prompt_snippet(self) -> str:
        """
        Returns a prompt snippet summarizing currently enabled MCP servers and their tools.
        """
        tools = self.get_active_tools()
        if not tools:
            return ""
        lines = ["Available MCP tools in system context:"]
        for t in tools:
            fn = t.get("function", {})
            desc = fn.get("description", "")
            lines.append(f"- {fn.get('name')} (from {t.get('_mcp_server')}) — {desc}")
        return "\n".join(lines)
