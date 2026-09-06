"""CLI commands for managing MCP servers."""
from __future__ import annotations

import shlex
import sys
from typing import Any, Optional

from core.infrastructure.platform.paths import CONFIG_DIR
from core.interfaces.cli.formatter import format_table

if False:  # type checking only
    from core.infrastructure.mcp import MCPManager


def _get_mcp_mgr(mgr: Optional[MCPManager] = None) -> MCPManager:
    if mgr is not None:
        return mgr
    from core.infrastructure.mcp import get_mcp_manager

    return get_mcp_manager()


def list_mcp(mgr: Optional[MCPManager] = None) -> int:
    """Format and print table with configured MCP servers."""
    from core.infrastructure.mcp import MCPManager

    mgr = _get_mcp_mgr(mgr)

    servers = mgr.load_servers()
    headers = ["Server", "Scope", "Status", "Tools count", "Command/URL"]
    rows: list[list[str]] = []

    tools_by_server: dict[str, list[str]] = {}
    try:
        active_tools = mgr.get_active_tools()
        for t in active_tools:
            s_name = t.get("_mcp_server")
            t_name = t.get("_mcp_tool_name")
            if s_name and t_name:
                tools_by_server.setdefault(s_name, []).append(t_name)
    except Exception:
        pass

    for s in servers:
        name = s.get("name", "")
        scope = s.get("scope", "global")
        enabled = MCPManager.server_enabled(s)
        status = "enabled" if enabled else "disabled"

        tools = tools_by_server.get(name, [])
        if tools:
            count_str = str(len(tools))
        else:
            server_status = mgr.get_server_status(name) if hasattr(mgr, "get_server_status") else {}
            t_cnt = server_status.get("tools", 0) if isinstance(server_status, dict) else 0
            count_str = str(t_cnt)

        cmd = s.get("command")
        args = s.get("args") or []
        url = s.get("url")
        if cmd:
            cmd_url = f"{cmd} {' '.join(str(a) for a in args)}" if args else str(cmd)
        elif url:
            cmd_url = str(url)
        else:
            cmd_url = "(none)"

        rows.append([name, scope, status, count_str, cmd_url])

    print(format_table(headers, rows))
    return 0


def add_mcp(
    name: str,
    cmd: Optional[str] = None,
    url: Optional[str] = None,
    args: Optional[list[str]] = None,
    scope: str = "global",
    mgr: Optional[MCPManager] = None,
) -> int:
    """Add or update an MCP server configuration."""
    if not name:
        print("Error: MCP server name is required.", file=sys.stderr)
        return 1
    if not cmd and not url:
        print("Error: Either --cmd or --url must be specified.", file=sys.stderr)
        return 1

    if cmd and isinstance(cmd, str) and " " in cmd.strip() and not args:
        parts = shlex.split(cmd)
        if parts:
            cmd = parts[0]
            args = parts[1:]

    mgr = _get_mcp_mgr(mgr)

    mgr.add_server(name, cmd=cmd, url=url, args=args, scope=scope)
    print(f"MCP server '{name}' added ({scope}).")
    return 0


def rm_mcp(name: str, scope: Optional[str] = None, mgr: Optional[MCPManager] = None) -> int:
    """Remove an MCP server configuration."""
    if not name:
        print("Error: MCP server name is required.", file=sys.stderr)
        return 1

    mgr = _get_mcp_mgr(mgr)

    removed = mgr.remove_server(name, scope=scope)
    if not removed:
        print(f"Error: MCP server '{name}' not found.", file=sys.stderr)
        return 1
    print(f"MCP server '{name}' removed.")
    return 0


def enable_mcp(name: str, scope: Optional[str] = None, mgr: Optional[MCPManager] = None) -> int:
    """Enable an MCP server."""
    if not name:
        print("Error: MCP server name is required.", file=sys.stderr)
        return 1

    mgr = _get_mcp_mgr(mgr)

    updated = mgr.set_server_enabled(name, True, scope=scope)
    if not updated:
        print(f"Error: MCP server '{name}' not found.", file=sys.stderr)
        return 1
    print(f"MCP server '{name}' enabled.")
    return 0


def disable_mcp(name: str, scope: Optional[str] = None, mgr: Optional[MCPManager] = None) -> int:
    """Disable an MCP server."""
    if not name:
        print("Error: MCP server name is required.", file=sys.stderr)
        return 1

    mgr = _get_mcp_mgr(mgr)

    updated = mgr.set_server_enabled(name, False, scope=scope)
    if not updated:
        print(f"Error: MCP server '{name}' not found.", file=sys.stderr)
        return 1
    print(f"MCP server '{name}' disabled.")
    return 0


def run_mcp(args: Any = None, mgr: Optional[MCPManager] = None) -> int:
    """Execute mcp subcommand based on parsed arguments."""
    action = getattr(args, "mcp_action", None) if args is not None else None

    if action is None or action == "list":
        return list_mcp(mgr)
    if action == "add":
        return add_mcp(
            getattr(args, "name", ""),
            cmd=getattr(args, "cmd", None),
            url=getattr(args, "url", None),
            args=getattr(args, "args", None),
            scope=getattr(args, "scope", "global"),
            mgr=mgr,
        )
    if action == "rm":
        return rm_mcp(getattr(args, "name", ""), scope=getattr(args, "scope", None), mgr=mgr)
    if action == "enable":
        return enable_mcp(getattr(args, "name", ""), scope=getattr(args, "scope", None), mgr=mgr)
    if action == "disable":
        return disable_mcp(getattr(args, "name", ""), scope=getattr(args, "scope", None), mgr=mgr)

    print(f"Error: Unknown mcp action '{action}'", file=sys.stderr)
    return 1


def print_mcp() -> None:
    """Print configured MCP servers to stdout (legacy format)."""
    from core.infrastructure.mcp import MCPManager, get_mcp_manager

    mgr = get_mcp_manager()
    servers = mgr.load_servers()
    print("Configured MCP Servers:")
    if not servers:
        print(f"  No MCP servers configured ({CONFIG_DIR}/mcp.json or .johnston/mcp.json)")
        return

    tools_by_server: dict[str, list[str]] = {}
    try:
        active_tools = mgr.get_active_tools()
        for t in active_tools:
            s_name = t.get("_mcp_server")
            t_name = t.get("_mcp_tool_name")
            if s_name and t_name:
                tools_by_server.setdefault(s_name, []).append(t_name)
    except Exception:
        pass

    for idx, s in enumerate(servers):
        enabled = MCPManager.server_enabled(s)
        status = "[enabled]" if enabled else "[disabled]"
        scope = f"[{s.get('scope', 'global')}]"
        name = s.get("name")

        cmd = s.get("command")
        args = s.get("args") or []
        url = s.get("url")
        if cmd:
            cmd_str = f"Command: {cmd}" + (f" {' '.join(str(a) for a in args)}" if args else "")
        elif url:
            cmd_str = f"URL: {url}"
        else:
            cmd_str = "Command: (none)"

        print(f"  * {name} {scope} {status}")
        print(f"    {cmd_str}")

        if not enabled:
            if idx < len(servers) - 1:
                print()
            continue

        tools = tools_by_server.get(name, [])
        if tools:
            print(f"    Tools: {', '.join(tools)}")
        elif url and not cmd:
            print("    Error: HTTP/SSE URL transport not supported yet (only stdio commands supported)")
        else:
            server_status = mgr.get_server_status(name) if hasattr(mgr, "get_server_status") else {}
            err = server_status.get("error") if isinstance(server_status, dict) else None
            if err:
                print(f"    Error: {err}")
            elif not cmd:
                print("    Error: Server configuration missing 'command' or 'url'")
            else:
                print("    Error: No tools reported or server failed to respond")

        if idx < len(servers) - 1:
            print()
