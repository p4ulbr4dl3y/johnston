"""Access bundled default skill definitions from package data.

Each default skill lives as a directory ``<skill_name>/`` under
``core/domain/defaults/skills/`` containing ``SKILL.md`` and optional extra files
(e.g. ``johnston-guide/references/*.md``). Bundled skills are loaded on the fly
as domain Skill entities (with SkillScope.BUNDLED) without copying files to disk.
"""

import os
from importlib import resources
from typing import List

from johnston_core.domain.entities.skills import Skill, SkillScope
from johnston_core.infrastructure.runtime.frontmatter import parse_frontmatter

_PACKAGE = __package__


def _is_skill_dir(name: str) -> bool:
    return not name.startswith("_")


def list_bundled_skills() -> List[str]:
    """Return names of bundled default skills (sorted)."""
    names = []
    for entry in resources.files(_PACKAGE).iterdir():
        if entry.is_dir() and _is_skill_dir(entry.name):
            names.append(entry.name)
    return sorted(names)


def load_bundled_skills() -> List[Skill]:
    """Load all bundled default skills as domain Skill entities."""
    skills = []
    for name in list_bundled_skills():
        base = resources.files(_PACKAGE).joinpath(name)
        skill_md = base.joinpath("SKILL.md")
        try:
            raw_content = skill_md.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = parse_frontmatter(raw_content)
        skill_name = fm.get("name") or name
        desc = fm.get("description", "").strip()
        if not desc and body:
            lines = [
                line.strip("# ").strip()
                for line in body.splitlines()
                if line.strip() and not line.startswith("#")
            ]
            desc = lines[0] if lines else ""
        is_hidden = str(fm.get("hidden", "")).lower() in ("true", "1", "yes")

        loc_str = ""
        try:
            p_str = str(skill_md)
            if os.path.exists(p_str):
                loc_str = p_str
        except Exception:
            pass

        skills.append(
            Skill(
                name=skill_name,
                description=desc,
                location=loc_str,
                content=body.strip(),
                scope=SkillScope.BUNDLED,
                hidden=is_hidden,
            )
        )
    return skills

