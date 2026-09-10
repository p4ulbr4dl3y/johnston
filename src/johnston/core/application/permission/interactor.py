"""Permission business logic facade — absorbs TUI-side permission operations.

All functions are pure-core (no Textual imports). They delegate to
PermissionManager and domain policies, keeping the TUI as a thin renderer.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from johnston.core.application.permission.helpers import get_global_config_file
from johnston.core.application.permission.permission_manager import PermissionManager
from johnston.core.domain.policies.permission_policy import (
    ExecutionMode,
    extract_tool_target_value,
    is_path_within_workspace,
    suggest_pattern,
)
from johnston.core.infrastructure.platform.platform_utils import read_json

__all__ = [
    "get_root_scope",
    "add_workspace_root",
    "remove_workspace_root",
    "cycle_execution_mode",
    "apply_permission_choice",
    "build_permission_options",
]

# Strings used as option keys in the permission confirmation UI.
ALLOW_ONCE = "allow"
ALWAYS_ALLOW = "always_allow"
ALWAYS_ALLOW_PROJECT = "always_allow:project"
DENY = "deny"
REJECT_REASON = "reject_reason"


def cycle_execution_mode() -> ExecutionMode:
    """Cycles the session execution mode: review -> edits -> yolo -> review.

    Returns the newly activated ExecutionMode.
    """
    pm = PermissionManager.get_instance()
    cur = pm.execution_mode
    if cur == ExecutionMode.REVIEW:
        nxt = ExecutionMode.EDITS
    elif cur == ExecutionMode.EDITS:
        nxt = ExecutionMode.YOLO
    else:
        nxt = ExecutionMode.REVIEW
    return pm.set_session_mode(nxt)


def apply_permission_choice(result: str, perm_name: str | None = None) -> bool | str:
    """Applies the user's permission-confirmation choice to PermissionManager.

    result is the raw string emitted by the permission confirmation screen:
    - ``"always_allow"`` / ``"always_allow:project"`` — session/project tool override
    - ``"server_allow:<pattern>"`` (+ optional ``:project`` suffix) — MCP server-wide override
    - ``"pattern:<pattern>"`` (+ optional ``:project`` suffix) — pattern override
    - ``"add_root:<path>"`` — persist a new workspace root
    - ``"deny"`` / ``"deny:<reason>"`` — pass through as the deny string
    - anything else — treated as a plain grant iff it equals an allow key

    Returns True when permission was granted, False otherwise, or the deny
    string for deny decisions (same semantics as the former ``confirm_permission``).
    """
    pm = PermissionManager.get_instance()
    if result == ALWAYS_ALLOW:
        if perm_name:
            pm.set_session_override(perm_name, "allow")
    elif result == ALWAYS_ALLOW_PROJECT:
        if perm_name:
            pm.save_tool_permission(perm_name, "allow", scope="auto")
    elif isinstance(result, str) and result.startswith("server_allow:"):
        pattern = _split_key(result, "server_allow:")
        if pattern:
            if _is_project_key(result):
                pm.save_tool_permission(pattern, "allow", scope="auto")
            else:
                pm.set_session_override(pattern, "allow")
        return True
    elif isinstance(result, str) and result.startswith("pattern:"):
        pattern = _split_key(result, "pattern:")
        if perm_name and pattern:
            if _is_project_key(result):
                pm.save_pattern_permission(perm_name, pattern, "allow", scope="auto")
            else:
                pm.set_session_pattern_override(perm_name, pattern, "allow")
    elif isinstance(result, str) and result.startswith("add_root:"):
        root_path = result.split(":", 1)[1]
        pm.save_workspace_root(root_path, scope="auto")
        return True
    elif isinstance(result, str) and result.startswith("deny:"):
        return result
    return result in (
        ALLOW_ONCE,
        ALWAYS_ALLOW,
        ALWAYS_ALLOW_PROJECT,
    ) or (
        isinstance(result, str)
        and (
            result.startswith("pattern:")
            or result.startswith("add_root:")
            or result.startswith("server_allow:")
        )
    )


def build_permission_options(
    tool_name: str,
    args: Dict[str, Any],
    server_name: str = "",
) -> Tuple[List[Tuple[str, str]], str]:
    """Builds the raw permission-confirmation options and the suggested pattern.

    Returns ``(raw_options, suggested_pattern)`` where ``raw_options`` is a list
    of ``(label, key)`` pairs and ``suggested_pattern`` is the pattern suggested
    for the tool invocation (may be empty). Option keys are consumed by
    :func:`apply_permission_choice`.
    """
    raw_options: List[Tuple[str, str]] = []
    raw_options.append(("Allow once", ALLOW_ONCE))

    server = (server_name or "").strip()
    is_mcp = bool(server or "__" in tool_name)
    if not server and is_mcp:
        server = tool_name.split("__", 1)[0].strip()

    suggested = suggest_pattern(tool_name, args) or ""

    if suggested:
        pat_clean = " ".join(suggested.split())
        raw_options.append((f'Allow pattern "{pat_clean}" [dim](session)[/]', f"pattern:{suggested}"))

    raw_options.append((f'Always allow "{tool_name}" [dim](session)[/]', ALWAYS_ALLOW))

    if is_mcp and server:
        raw_options.append(
            (f'Always allow ALL tools from "{server}" [dim](session)[/]', f"server_allow:{server}__*")
        )

    if suggested:
        pat_clean = " ".join(suggested.split())
        raw_options.append((f'Allow pattern "{pat_clean}" [dim](project)[/]', f"pattern:{suggested}:project"))

    raw_options.append((f'Always allow "{tool_name}" [dim](project)[/]', ALWAYS_ALLOW_PROJECT))

    if is_mcp and server:
        raw_options.append(
            (f'Always allow ALL tools from "{server}" [dim](project)[/]', f"server_allow:{server}__*:project")
        )

    pm = PermissionManager.get_instance()
    nargs = args if isinstance(args, dict) else {}
    target_path = (
        (nargs.get("cwd") if tool_name == "shell" else "")
        or extract_tool_target_value(tool_name, args)
        or nargs.get("path")
        or ""
    )
    if target_path and isinstance(target_path, str) and not is_path_within_workspace(target_path, pm.get_workspace_roots()):
        if os.path.isdir(target_path) or (tool_name == "shell" and nargs.get("cwd") == target_path):
            root_to_add = target_path
        else:
            root_to_add = os.path.dirname(target_path) or target_path
        norm_root = os.path.realpath(os.path.abspath(os.path.expanduser(root_to_add)))
        # Never offer the filesystem root (e.g. "/" for a nonexistent
        # top-level file — it would unboundedly widen the workspace), and
        # never offer a path already inside the workspace.
        if (
            norm_root
            and norm_root != os.path.abspath(os.sep)
            and not is_path_within_workspace(norm_root, pm.get_workspace_roots())
        ):
            raw_options.append((f'Add "{_ellipsize(root_to_add, 36)}" to roots [dim](workspace)[/]', f"add_root:{root_to_add}"))

    raw_options.append(("Deny", DENY))
    raw_options.append(("Reject with feedback...", REJECT_REASON))
    return raw_options, suggested


def add_workspace_root(path: str, *, scope: str = "auto") -> None:
    """Persists a workspace root, delegating to the PermissionManager singleton.

    scope matches ``save_workspace_root`` ('session', 'local', 'project', or
    'auto'). The default 'auto' resolves to local when the project is a git
    repository, else project.
    """
    PermissionManager.get_instance().save_workspace_root(path, scope=scope)


def remove_workspace_root(path: str, *, project_dir: str | None = None) -> None:
    """Removes a workspace root from memory and persisted config.

    project_dir resolves the project config directory; defaults to the current
    project dir on the PermissionManager singleton.
    """
    PermissionManager.get_instance().remove_persisted_workspace_root(path, project_dir=project_dir)


def get_root_scope(path: str) -> str:
    """Determines the scope of a workspace root path.

    Returns the scope of the root path: 'primary', 'project', 'local', 'global',
    or 'session'. The first matching config layer wins, matching the previous
    TUI-side implementation.
    """
    pm = PermissionManager.get_instance()
    norm = os.path.realpath(os.path.abspath(path))
    primary = os.path.realpath(os.path.abspath(pm.current_project_dir or os.getcwd()))
    if norm == primary:
        return "primary"

    pdir = primary
    for cfg_file, scope in (("config.local.json", "local"), ("config.json", "project")):
        target = os.path.join(pdir, ".johnston", cfg_file)
        if os.path.isfile(target):
            data = read_json(target, default={})
            if isinstance(data, dict) and any(
                os.path.realpath(os.path.abspath(r)) == norm
                for r in data.get("permissions", {}).get("writable_roots", [])
                if isinstance(r, str)
            ):
                return scope

    if os.path.isfile(get_global_config_file()):
        data = read_json(get_global_config_file(), default={})
        if isinstance(data, dict) and any(
            os.path.realpath(os.path.abspath(r)) == norm
            for r in data.get("permissions", {}).get("writable_roots", [])
            if isinstance(r, str)
        ):
            return "global"

    return "session"


def _is_project_key(key: str) -> bool:
    """True when an option key carries the ``:project`` persist suffix."""
    return key.endswith(":project")


def _split_key(key: str, prefix: str) -> str:
    """Extracts the payload from a prefixed option key, stripping the ``:project`` suffix."""
    payload = key[len(prefix):]
    if payload.endswith(":project"):
        payload = payload[: -len(":project")]
    return payload


def _ellipsize(text: str, max_width: int) -> str:
    """Clips text to at most ``max_width`` characters, appending ``...`` when truncated."""
    if len(text) <= max_width:
        return text
    return text[: max(0, max_width - 3)] + "..."
