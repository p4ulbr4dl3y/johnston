"""
Skill Manager for Johnston.
Handles global skills (~/.johnston/skills/) and project-level skills (<cwd>/.johnston/skills/).
Each skill is a directory whose SKILL.md carries optional YAML frontmatter
(name, description, hidden).
"""

import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from core.domain.defaults.git_excludes import DEFAULT_IGNORE_DIRS
from core.domain.defaults.skills.loader import BundledSkill, get_bundled_skill, list_bundled_skills
from core.infrastructure.platform.paths import CONFIG_DIR
from core.infrastructure.platform.platform_utils import atomic_write_text
from core.infrastructure.runtime.frontmatter import parse_frontmatter
from core.infrastructure.runtime.fs_signature import compute_dir_signature_recursive

logger = logging.getLogger(__name__)

GLOBAL_SKILLS_DIR = os.path.join(CONFIG_DIR, "skills")
PROJECT_SKILLS_DIR_NAME = os.path.join(".johnston", "skills")

__all__ = [
    "GLOBAL_SKILLS_DIR",
    "PROJECT_SKILLS_DIR_NAME",
    "Skill",
    "SkillManager",
    "SkillScope",
    "get_skill_manager",
]


class SkillScope(Enum):
    """Domain scope of a discovered skill."""

    GLOBAL = "global"
    PROJECT = "project"


@dataclass
class Skill:
    """Structured representation of a discovered skill."""

    name: str
    description: str
    location: str
    content: str
    scope: SkillScope
    hidden: bool

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the dict shape previously emitted for UI/JSON consumers."""
        return {
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "content": self.content,
            "scope": self.scope.value,
            "hidden": self.hidden,
        }


class SkillManager:
    """Discovers skills in the global and project trees with signature-based caching.

    Construction is side-effect free; use :func:`get_skill_manager` to obtain the
    shared, provisioning instance.
    """

    _CACHE_TTL = 2.0  # seconds

    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_dir = GLOBAL_SKILLS_DIR
        self.project_dir_skills = os.path.join(self.project_dir, PROJECT_SKILLS_DIR_NAME)
        self._scan_signature: Optional[tuple] = None
        self._scan_cache: Optional[List[Skill]] = None
        self._scan_ts: float = 0.0

    def list_skills(
        self,
        include_hidden: bool = True,
        for_system_prompt: bool = False,
    ) -> List[Skill]:
        """
        Discovers skills in global and project directories.
        Project skills override global skills with the same name.

        Full scans are cached in-memory and invalidated when the on-disk skill
        trees change (via a cheap directory signature) or after a short TTL.
        """
        now = time.time()
        if self._scan_cache is not None and (now - self._scan_ts) < self._CACHE_TTL:
            skills = self._scan_cache
        else:
            sig = self._compute_scan_signature()
            if self._scan_cache is not None and self._scan_signature == sig:
                self._scan_ts = now
                skills = self._scan_cache
            else:
                skills, signature = self._scan_skills()
                self._scan_cache = skills
                self._scan_signature = signature
                self._scan_ts = now

        result = []
        for s in skills:
            if (for_system_prompt or not include_hidden) and s.hidden:
                continue
            result.append(s)
        return result

    @staticmethod
    def _filter_scan_dirs(dirs: List[str]) -> None:
        """In-place filter of os.walk dirs to skip ignored and dot-directories."""
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]

    def _compute_scan_signature(self) -> Optional[tuple]:
        """Cheap signature of (path, mtime_ns, size) for every SKILL.md under
        both global and project trees, detecting external changes without
        re-reading contents."""
        def _skip(subdir: str) -> bool:
            return subdir in DEFAULT_IGNORE_DIRS or subdir.startswith(".")

        entries = compute_dir_signature_recursive(
            [self.global_dir, self.project_dir_skills],
            filenames=["SKILL.md"],
            skip_dir=_skip,
        )
        return tuple(entries)

    def _scan_skills(self) -> tuple:
        """Scans both skill trees in a single walk, returning (skills, signature).
        The signature is computed from the same walk that discovers skills, so a
        cache miss costs exactly one full tree traversal instead of two or three.
        """
        skills_map: Dict[str, Skill] = {}
        signature_entries: List[tuple] = []
        real_global = os.path.realpath(self.global_dir)
        real_project = os.path.realpath(self.project_dir_skills)

        for scope, dir_path in [("global", self.global_dir), ("project", self.project_dir_skills)]:
            if scope == "project" and real_project == real_global:
                continue
            if not os.path.isdir(dir_path):
                continue

            md_files = []
            walker = os.walk(dir_path)
            for root, dirs, files in walker:
                self._filter_scan_dirs(dirs)
                for f in files:
                    fpath = os.path.join(root, f)
                    if f == "SKILL.md":
                        md_files.append(fpath)
                        try:
                            st = os.stat(fpath)
                            signature_entries.append((fpath, st.st_mtime_ns, st.st_size))
                        except OSError:
                            pass

            for filepath in sorted(md_files):
                try:
                    with open(filepath, "r", encoding="utf-8") as file:
                        raw_content = file.read()
                except Exception:
                    logger.debug("Skipping unreadable skill file: %s", filepath, exc_info=True)
                    continue

                fm, body = parse_frontmatter(raw_content)

                name = fm.get("name")
                if not name:
                    name = os.path.basename(os.path.dirname(filepath))

                if not name or name.startswith("."):
                    continue

                desc = fm.get("description", "").strip()
                if not desc and body:
                    lines = [
                        line.strip("# ").strip()
                        for line in body.splitlines()
                        if line.strip() and not line.startswith("#")
                    ]
                    desc = lines[0] if lines else ""

                is_hidden = str(fm.get("hidden", "")).lower() in ("true", "1", "yes")

                skills_map[name] = Skill(
                    name=name,
                    description=desc,
                    location=filepath,
                    content=body.strip(),
                    scope=SkillScope(scope),
                    hidden=is_hidden,
                )

        skills = list(skills_map.values())
        return skills, tuple(signature_entries)

    def invalidate_cache(self) -> None:
        """Force the next list_skills/get_skill to re-scan both skill trees."""
        self._scan_signature = None
        self._scan_cache = None
        self._scan_ts = 0.0

    def get_skill(self, name: str, include_hidden: bool = True) -> Optional[Skill]:
        skills = self.list_skills(include_hidden=include_hidden)
        for s in skills:
            if s.name.lower() == name.lower():
                return s
        return None

    def toggle_hidden(self, name: str) -> bool:
        """
        Toggles the 'hidden' attribute of a skill in its frontmatter.
        Returns the new hidden state (True = hidden, False = visible).

        Raises KeyError for an unknown skill. Write failures are logged and
        re-raised so callers stay in sync with disk instead of silently
        diverging from it.
        """
        skill = self.get_skill(name, include_hidden=True)
        if not skill or not skill.location:
            raise KeyError(f"Unknown skill: {name!r}")

        filepath = skill.location
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            new_hidden = not skill.hidden

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    fm_lines = parts[1].splitlines()
                    new_fm_lines = []
                    found_hidden = False

                    for line in fm_lines:
                        sline = line.strip().lower()
                        if sline.startswith("hidden:"):
                            found_hidden = True
                            new_fm_lines.append(f"hidden: {str(new_hidden).lower()}")
                        else:
                            new_fm_lines.append(line)

                    if not found_hidden:
                        new_fm_lines.append(f"hidden: {str(new_hidden).lower()}")

                    new_fm_str = "\n".join(line_item for line_item in new_fm_lines if line_item.strip())
                    body = parts[2].lstrip("\r\n")
                    new_content = f"---\n{new_fm_str}\n---\n{body}"
                else:
                    new_content = f"---\nhidden: {str(new_hidden).lower()}\n---\n{content}"
            else:
                new_content = f"---\nhidden: {str(new_hidden).lower()}\n---\n{content}"

            atomic_write_text(filepath, new_content)
            self.invalidate_cache()

            return new_hidden
        except Exception:
            logger.warning("Failed to toggle hidden for skill %r (%s)", name, filepath, exc_info=True)
            raise

    def get_system_prompt_skills(self) -> List[Skill]:
        """Return non-hidden skills for the system prompt.

        Data-only: leaves Markdown bullet assembly to the prompt builder so this
        application module does not own rendering output.
        """
        return self.list_skills(include_hidden=False, for_system_prompt=True)


# Shared per-process managers keyed by resolved project dir, so every consumer
# (UI screens, command providers, prompt builder) shares one scan cache and one
# provisioning step instead of each instantiating its own manager.
_SKILL_MANAGERS: Dict[str, SkillManager] = {}
_registry_lock = threading.Lock()
_bundled_provisioned = False


def _provision_skill_files(skill: BundledSkill) -> None:
    """Write a bundled skill's files into the global skills dir if missing.

    Existing files are left untouched so users can edit/remove their local
    copies. Individual failures are logged and skipped.
    """
    skill_dir = os.path.join(GLOBAL_SKILLS_DIR, skill.name)
    for rel_path, content in skill.files.items():
        target_path = os.path.join(skill_dir, rel_path)
        if os.path.exists(target_path):
            continue
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            atomic_write_text(target_path, content)
        except Exception:
            logger.warning("Failed to write skill file: %s", target_path, exc_info=True)


def get_skill_manager(project_dir: Optional[str] = None) -> SkillManager:
    """Return the shared SkillManager for ``project_dir`` (defaults to cwd).

    Managers are cached by resolved project dir so repeated calls reuse one
    scan cache/TTL window. The first call also creates the global skills dir
    and provisions bundled default skills into it (once per process).
    """
    global _bundled_provisioned
    key = os.path.realpath(project_dir or os.getcwd())
    with _registry_lock:
        mgr = _SKILL_MANAGERS.get(key)
        if mgr is None:
            if not _bundled_provisioned:
                os.makedirs(GLOBAL_SKILLS_DIR, exist_ok=True)
                for name in list_bundled_skills():
                    _provision_skill_files(get_bundled_skill(name))
                _bundled_provisioned = True
            mgr = SkillManager(project_dir=key)
            _SKILL_MANAGERS[key] = mgr
        return mgr

