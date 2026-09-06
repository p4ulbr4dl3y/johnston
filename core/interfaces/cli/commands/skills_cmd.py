"""CLI skills command."""
from __future__ import annotations

from typing import Any


def run_skills(args: Any = None) -> int:
    """Print available skills to stdout."""
    from core.application.skills.manager import SkillManager
    from core.infrastructure.platform.paths import CONFIG_DIR

    skills = SkillManager().list_skills()
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
