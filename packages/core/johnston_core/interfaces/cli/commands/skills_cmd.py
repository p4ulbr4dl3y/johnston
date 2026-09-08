"""CLI skills command."""
from __future__ import annotations

from typing import Any


def run_skills(args: Any = None) -> int:
    """Print available skills to stdout or JSON."""
    import json

    from johnston_core.application.skills.manager import SkillManager
    from johnston_core.infrastructure.platform.paths import CONFIG_DIR

    skills = SkillManager().list_skills()
    as_json = bool(getattr(args, "json", False)) if args else False

    if as_json:
        data = [
            {
                "name": s.name,
                "scope": s.scope.value if hasattr(s.scope, "value") else str(s.scope),
                "hidden": bool(s.hidden),
                "description": getattr(s, "description", "") or "",
            }
            for s in skills
        ]
        print(json.dumps(data, indent=2))
        return 0

    print("Available Johnston Skills:")
    if not skills:
        print(f"  No skills found ({CONFIG_DIR}/skills/ or .johnston/skills/)")
        return 0
    for s in skills:
        scope = f"[{s.scope.value}]"
        hidden = " [hidden]" if s.hidden else ""
        print(f"  * {s.name} {scope}{hidden}")
    return 0


def print_skills() -> None:
    """Backward-compatible helper for legacy callers."""
    run_skills()
