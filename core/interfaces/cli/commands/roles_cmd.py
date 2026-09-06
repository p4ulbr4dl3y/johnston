"""CLI roles command."""
from __future__ import annotations

from typing import Any


def run_roles(args: Any = None) -> int:
    """Print available unified agent roles to stdout."""
    from core.role_registry import RoleRegistry

    registry = RoleRegistry.get_instance()
    roles = registry.load_roles()
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
