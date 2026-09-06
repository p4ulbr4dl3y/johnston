"""CLI doctor command for diagnosing environment, configuration, providers, and tools."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from typing import Any, List, Optional, Tuple

from core.domain.defaults.providers import DEFAULT_JSON_PROVIDERS
from core.infrastructure.mcp import MCPManager, get_mcp_manager
from core.infrastructure.platform import paths
from core.interfaces.cli.formatter import GREEN, RED, RESET, YELLOW, supports_color
from core.provider_manager import ProviderManager, is_local_provider

__all__ = [
    "diagnose_config_dirs",
    "diagnose_git",
    "diagnose_mcp",
    "diagnose_providers",
    "diagnose_python",
    "diagnose_uv",
    "format_checklist_item",
    "run_doctor",
]


def format_checklist_item(symbol: str, message: str, colorize: bool = True) -> str:
    """Format a checklist line with status badge and optional ANSI coloring."""
    if colorize and supports_color():
        if symbol == "✓":
            badge = f"{GREEN}[✓]{RESET}"
        elif symbol == "✗":
            badge = f"{RED}[✗]{RESET}"
        else:
            badge = f"{YELLOW}[!]{RESET}"
    else:
        badge = f"[{symbol}]"
    return f"  {badge} {message}"


def diagnose_python() -> Tuple[str, str]:
    """Check current Python runtime version."""
    v = sys.version_info
    major = getattr(v, "major", v[0])
    minor = getattr(v, "minor", v[1])
    micro = getattr(v, "micro", v[2])
    py_ver = f"{major}.{minor}.{micro}"
    if (3, 10) <= (major, minor) < (3, 14):
        return ("✓", f"Python runtime: v{py_ver} (supported 3.10+)")
    return ("!", f"Python runtime: v{py_ver} (recommended 3.10 - 3.13)")


def diagnose_uv() -> Tuple[str, str]:
    """Check uv package manager availability and version."""
    uv_bin = shutil.which("uv")
    if not uv_bin:
        return ("!", "uv package manager: not found in PATH (install via https://astral.sh/uv)")
    try:
        proc = subprocess.run([uv_bin, "--version"], capture_output=True, text=True, timeout=5)
        out = proc.stdout.strip() if proc.returncode == 0 else ""
        ver = out or "installed"
        return ("✓", f"uv package manager: {ver}")
    except Exception as err:
        return ("!", f"uv package manager: found at {uv_bin} but version check failed ({err})")


def diagnose_config_dirs(project_dir: Optional[str] = None) -> List[Tuple[str, str]]:
    """Check whether global and project configuration directories are writable."""
    results: List[Tuple[str, str]] = []

    # Global config directory
    global_dir = paths.CONFIG_DIR
    try:
        os.makedirs(global_dir, exist_ok=True)
        if os.access(global_dir, os.W_OK):
            results.append(("✓", f"Global config dir: {global_dir} (writable)"))
        else:
            results.append(("✗", f"Global config dir: {global_dir} (not writable)"))
    except OSError as err:
        results.append(("✗", f"Global config dir: {global_dir} (failed: {err})"))

    # Project config directory
    proj = os.path.realpath(project_dir or os.getcwd())
    proj_johnston = os.path.join(proj, ".johnston")
    try:
        if os.path.exists(proj_johnston):
            writable = os.access(proj_johnston, os.W_OK)
        else:
            writable = os.access(proj, os.W_OK)

        if writable:
            results.append(("✓", f"Project config dir: {proj_johnston} (writable)"))
        else:
            results.append(("✗", f"Project config dir: {proj_johnston} (not writable)"))
    except OSError as err:
        results.append(("✗", f"Project config dir: {proj_johnston} (failed: {err})"))

    return results


def diagnose_git(project_dir: Optional[str] = None) -> Tuple[str, str]:
    """Check git repository presence and working tree status."""
    git_bin = shutil.which("git")
    if not git_bin:
        return ("!", "Git: not found in PATH")

    proj = os.path.realpath(project_dir or os.getcwd())
    try:
        proc_tree = subprocess.run(
            [git_bin, "rev-parse", "--is-inside-work-tree"],
            cwd=proj,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc_tree.returncode != 0:
            return ("!", "Git repository: not inside a git repository")

        branch_proc = subprocess.run(
            [git_bin, "branch", "--show-current"],
            cwd=proj,
            capture_output=True,
            text=True,
            timeout=5,
        )
        branch = branch_proc.stdout.strip() or "HEAD"

        status_proc = subprocess.run(
            [git_bin, "status", "--porcelain"],
            cwd=proj,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if status_proc.returncode != 0:
            return ("!", f"Git repository: detected (branch: {branch}), unable to check status")

        changed_lines = [line for line in status_proc.stdout.splitlines() if line.strip()]
        if not changed_lines:
            return ("✓", f"Git repository: clean working tree (branch: {branch})")
        return ("!", f"Git repository: dirty working tree ({len(changed_lines)} uncommitted file(s), branch: {branch})")
    except Exception as err:
        return ("!", f"Git check failed: {err}")


def _ping_local_endpoint(base_url: str) -> Optional[bool]:
    """Test connection to local inference server with short timeout."""
    if not base_url or not any(h in base_url.lower() for h in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")):
        return None
    try:
        req = urllib.request.Request(base_url, headers={"User-Agent": "johnston-doctor"})
        with urllib.request.urlopen(req, timeout=0.3):
            return True
    except urllib.error.HTTPError:
        # Received HTTP response (e.g. 404, 405), server is alive
        return True
    except Exception:
        return False


def diagnose_providers(pm: Optional[ProviderManager] = None) -> List[Tuple[str, str]]:
    """Check status of configured LLM providers."""
    if pm is None:
        pm = ProviderManager()

    results: List[Tuple[str, str]] = []
    providers = pm.load_providers(include_disabled=True)
    if not providers:
        results.append(("!", "No LLM providers configured"))
        return results

    active_key = pm.get_active_provider_key() if hasattr(pm, "get_active_provider_key") else None
    disabled_keys = set(pm.get_disabled_providers()) if hasattr(pm, "get_disabled_providers") else set()

    unconfigured_default_count = 0
    many_providers = len(providers) > 5

    for pkey, pdata in providers.items():
        is_active = (pkey == active_key)
        is_disabled = (pkey in disabled_keys) or not pdata.get("enabled", True)
        pdef = pm.load_provider_def(pkey) if hasattr(pm, "load_provider_def") else None
        api_type = getattr(pdef, "api_type", "") if pdef else str(pdata.get("api_type", ""))
        base_url = getattr(pdef, "base_url", "") if pdef else str(pdata.get("base_url", ""))
        req_key = getattr(pdef, "requires_key", None) if pdef else pdata.get("requires_key")

        is_local = is_local_provider(pkey, api_type, base_url, req_key)
        api_key = (pm.get_api_key(pkey) if hasattr(pm, "get_api_key") else "") or pdata.get("api_key", "")
        model = (pm.get_provider_model(pkey) if hasattr(pm, "get_provider_model") else "") or pdata.get("model") or "-"

        is_custom = pkey not in DEFAULT_JSON_PROVIDERS
        has_key = bool(api_key and str(api_key).strip())

        # If many providers exist, summarize unused defaults without keys
        if many_providers and not is_active and not has_key and not is_local and not is_custom and not is_disabled:
            unconfigured_default_count += 1
            continue

        prefix = f"Provider '{pkey}'"
        if is_active:
            prefix += " (active)"

        if is_disabled:
            results.append(("!", f"{prefix}: disabled (model: {model})"))
        elif is_local:
            ping_ok = _ping_local_endpoint(base_url)
            ping_info = " (server reachable)" if ping_ok is True else ""
            results.append(("✓", f"{prefix}: ready (model: {model}, local inference{ping_info})"))
        elif has_key:
            results.append(("✓", f"{prefix}: ready (model: {model}, API key set)"))
        else:
            # Active provider or explicit provider missing required key
            results.append(("✗", f"{prefix}: API key unset (model: {model})"))

    if unconfigured_default_count > 0:
        results.append(("!", f"{unconfigured_default_count} other default provider(s) have no API key set"))

    return results


def diagnose_mcp(mgr: Optional[MCPManager] = None) -> List[Tuple[str, str]]:
    """Check configured MCP servers, command validity, and tool counts."""
    if mgr is None:
        mgr = get_mcp_manager()

    results: List[Tuple[str, str]] = []
    servers = mgr.load_servers()
    if not servers:
        results.append(("!", "No MCP servers configured"))
        return results

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
        name = s.get("name", "unnamed")
        enabled = MCPManager.server_enabled(s)
        if not enabled:
            results.append(("!", f"MCP server '{name}': disabled"))
            continue

        tools = tools_by_server.get(name, [])
        if tools:
            count = len(tools)
        else:
            server_status = mgr.get_server_status(name) if hasattr(mgr, "get_server_status") else {}
            count = server_status.get("tools", 0) if isinstance(server_status, dict) else 0

        cmd = s.get("command")
        url = s.get("url")

        if cmd:
            cmd_bin = (
                cmd[0]
                if isinstance(cmd, list)
                else (cmd.strip().split()[0] if isinstance(cmd, str) and cmd.strip() else "")
            )
            cmd_display = " ".join(cmd) if isinstance(cmd, list) else (cmd if isinstance(cmd, str) else str(cmd))
            if shutil.which(cmd_bin) or os.path.exists(cmd_bin):
                results.append(("✓", f"MCP server '{name}': command valid ('{cmd_display}'), {count} tool(s)"))
            else:
                results.append(("✗", f"MCP server '{name}': command not found ('{cmd_display}')"))
        elif url:
            if url.startswith(("http://", "https://")):
                results.append(("✓", f"MCP server '{name}': endpoint valid ('{url}'), {count} tool(s)"))
            else:
                results.append(("✗", f"MCP server '{name}': invalid URL ('{url}')"))
        else:
            results.append(("✗", f"MCP server '{name}': missing command or URL"))

    return results


def run_doctor(
    args: Any = None,
    pm: Optional[ProviderManager] = None,
    mcp_mgr: Optional[MCPManager] = None,
    project_dir: Optional[str] = None,
) -> int:
    """Execute diagnostic checks and print report."""
    print("Johnston Doctor - Diagnostic Report\n")

    sections: List[Tuple[str, List[Tuple[str, str]]]] = [
        ("Environment", [diagnose_python(), diagnose_uv()]),
        ("Configuration & Storage", diagnose_config_dirs(project_dir)),
        ("Git Repository", [diagnose_git(project_dir)]),
        ("LLM Providers", diagnose_providers(pm)),
        ("MCP Servers", diagnose_mcp(mcp_mgr)),
    ]

    has_errors = False
    has_warnings = False

    for title, items in sections:
        print(f"{title}:")
        for sym, msg in items:
            if sym == "✗":
                has_errors = True
            elif sym == "!":
                has_warnings = True
            print(format_checklist_item(sym, msg))
        print()

    if has_errors:
        print("Doctor found configuration issues that need attention.")
        return 1
    elif has_warnings:
        print("Doctor completed with warnings.")
        return 0

    print("All diagnostic checks passed successfully!")
    return 0
