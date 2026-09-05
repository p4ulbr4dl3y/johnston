import json
import logging
import os
from typing import Any, Dict, Optional, Set, Tuple

from core.infrastructure.platform.paths import CONFIG_DIR
from core.infrastructure.platform.platform_utils import update_json_config

logger = logging.getLogger("core.infrastructure.mcp.manager")

GLOBAL_MCP_FILE = os.path.join(CONFIG_DIR, "mcp.json")
PROJECT_MCP_FILE = os.path.join(".johnston", "mcp.json")


def ensure_global_config(global_file: str = GLOBAL_MCP_FILE) -> None:
    """Lazily materialize default global config if missing."""
    try:
        from core.infrastructure.config.config_helpers import ensure_json_config

        ensure_json_config(global_file, {"mcpServers": {}})
    except Exception:
        logger.debug("Failed to ensure default global MCP config", exc_info=True)


def server_enabled(server: Dict[str, Any]) -> bool:
    """True if server entry is enabled. Absent key means enabled."""
    return bool(server.get("enabled", True))


def command_parts_valid(cmd: Any) -> bool:
    """Validate server command before subprocess launch."""
    if isinstance(cmd, str):
        return True
    return isinstance(cmd, list) and bool(cmd) and all(isinstance(c, str) for c in cmd)


def servers_signature(global_file: str, project_file: str) -> Tuple:
    """Returns (path, mtime_ns, size) for both config files to detect changes."""
    sig = []
    for path in (global_file, project_file):
        try:
            st = os.stat(path)
            sig.append((path, st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((path, None, None))
    return tuple(sig)


def warn_broken_config(warned_files: Set[Tuple[str, str]], path: str, reason: str = "") -> None:
    key = (path, reason)
    if key in warned_files:
        return
    warned_files.add(key)
    base = f"Failed to load MCP servers config {path}"
    logger.warning("%s", f"{base}: {reason}" if reason else f"{base}: invalid JSON")


def load_config_file(
    path: str,
    scope: str,
    servers: Dict[str, Dict[str, Any]],
    warned_files: Optional[Set[Tuple[str, str]]] = None,
) -> None:
    """Parse one MCP config file into ``servers``, validating entries."""
    if not os.path.exists(path):
        return
    warned = warned_files if warned_files is not None else set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        warn_broken_config(warned, path)
        return

    mcp_servers = data.get("mcpServers") or {}
    if not isinstance(mcp_servers, dict):
        warn_broken_config(warned, path, reason="'mcpServers' must be an object")
        return

    for k, v in mcp_servers.items():
        if not isinstance(v, dict):
            warn_broken_config(warned, path, reason=f"server '{k}': entry must be an object")
            continue
        v_copy = dict(v)
        url = v_copy.get("url")
        cmd = v_copy.get("command")
        if url:
            if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
                warn_broken_config(warned, path, reason=f"server '{k}': invalid url {url!r}")
                continue
            v_copy["type"] = "sse"
            headers = v_copy.get("headers")
            if headers is not None and not isinstance(headers, dict):
                warn_broken_config(warned, path, reason=f"server '{k}': 'headers' must be an object")
                headers = None
            v_copy["headers"] = headers or {}
        else:
            if not command_parts_valid(cmd):
                warn_broken_config(warned, path, reason=f"server '{k}': invalid command {cmd!r}")
                continue
            args = v_copy.get("args")
            if args is not None and not isinstance(args, list):
                warn_broken_config(warned, path, reason=f"server '{k}': 'args' must be an array")
                args = None
            v_copy["args"] = args or []
            v_copy["type"] = "stdio"

        env = v_copy.get("env")
        if env is not None and not isinstance(env, dict):
            warn_broken_config(warned, path, reason=f"server '{k}': 'env' must be an object")
            env = None
        v_copy["env"] = env
        cwd = v_copy.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            warn_broken_config(warned, path, reason=f"server '{k}': 'cwd' must be a string")
            cwd = None
        v_copy["cwd"] = cwd
        v_copy["name"] = k
        v_copy["scope"] = scope
        servers[k] = v_copy


def update_server_config(
    global_file: str,
    project_file: str,
    target: Dict[str, Any],
    name: str,
    key_updates: Dict[str, Any],
) -> None:
    """Read-modify-write MCP server config files atomically."""
    file_to_update = (
        project_file
        if target.get("scope") == "project" and os.path.exists(project_file)
        else global_file
    )

    def _mutate(cfg: Dict[str, Any]) -> None:
        cfg.setdefault("mcpServers", {})
        if name in cfg["mcpServers"]:
            entry = cfg["mcpServers"][name]
            entry.update(key_updates)
        else:
            entry = {
                "command": target.get("command"),
                "args": target.get("args"),
                "env": target.get("env"),
                "url": target.get("url"),
            }
            entry.update(key_updates)
            cfg["mcpServers"][name] = entry

        if entry.get("enabled", True) is not False:
            entry.pop("enabled", None)

    update_json_config(file_to_update, _mutate, indent=2)
