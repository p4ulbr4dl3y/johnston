"""CLI roles command."""
from __future__ import annotations

from typing import Any


def run_roles(args: Any = None) -> int:
    """Print available unified agent roles to stdout or JSON."""
    import json

    from johnston.core.roles.role_registry import RoleRegistry

    registry = RoleRegistry.get_instance()
    roles = registry.load_roles()
    as_json = bool(getattr(args, "json", False)) if args else False

    if as_json:
        data = [
            {
                "name": r.name,
                "key": r.key,
                "scope": r.scope,
                "source": r.source,
                "description": r.description or "",
                "model": f"{r.provider}/{r.model}" if r.provider and r.model else (r.model or ""),
                "read_only": r.read_only,
                "allowed_tools": r.allowed_tools or [],
                "disallowed_tools": r.disallowed_tools or [],
            }
            for _, r in roles.items()
        ]
        print(json.dumps(data, indent=2))
        return 0

    print("Available Agent Roles & Modes:")
    role_list = list(roles.items())
    for idx, (key, r) in enumerate(role_list):
        scope_str = f" [scope: {r.scope}]" if r.scope != "any" else ""
        print(f"  * {r.name} ({r.key}){scope_str} [{r.source}]")
        if r.description:
            print(f"    Description: {r.description}")
        if r.disallowed_tools:
            print(f"    Disallowed tools: {', '.join(r.disallowed_tools)}")
        if r.allowed_tools:
            print(f"    Allowed tools: {', '.join(r.allowed_tools)}")
        if idx < len(role_list) - 1:
            print()
    return 0


def print_roles() -> None:
    """Backward-compatible helper for legacy callers."""
    run_roles()
