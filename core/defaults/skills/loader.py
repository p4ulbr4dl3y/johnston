"""Access bundled default skill definitions from package data.

Each default skill lives as a directory ``<skill_name>/`` under
``core/defaults/skills/`` containing ``SKILL.md`` and optional extra files
(e.g. ``johnston-guide/references/*.md``). These are provisioned into the
user's global skills directory on first run. Bundled files are read via
:mod:`importlib.resources` so they also work from an installed wheel.
"""

from dataclasses import dataclass
from importlib import resources
from typing import Dict, List

_PACKAGE = __package__


@dataclass(frozen=True)
class BundledSkill:
    """A bundled default skill directory."""

    name: str
    files: Dict[str, str]  # rel_path within skill dir -> content


def _is_skill_dir(name: str) -> bool:
    return not name.startswith("_")


def list_bundled_skills() -> List[str]:
    """Return names of bundled default skills (sorted)."""
    names = []
    for entry in resources.files(_PACKAGE).iterdir():
        if entry.is_dir() and _is_skill_dir(entry.name):
            names.append(entry.name)
    return sorted(names)


def _collect_files(base) -> Dict[str, str]:
    """Recursively collect {rel_path: content} under a Traversable dir."""
    files: Dict[str, str] = {}
    for entry in base.iterdir():
        if entry.name.endswith(".pyc"):
            continue
        rel_path = entry.name
        if entry.is_dir():
            for sub_rel, content in _collect_files(entry).items():
                files[f"{rel_path}/{sub_rel}"] = content
        else:
            files[rel_path] = entry.read_text(encoding="utf-8").strip()
    return files


def get_bundled_skill(name: str) -> BundledSkill:
    """Return a bundled skill's files as {rel_path: content}."""
    base = resources.files(_PACKAGE).joinpath(name)
    if not base.is_dir() or not _is_skill_dir(name):
        raise KeyError(f"No bundled skill named {name!r}")
    return BundledSkill(name=name, files=_collect_files(base))
