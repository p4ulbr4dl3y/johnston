"""
Skill Manager for Johnston.
Handles global skills (~/.johnston/skills/) and project-level skills (<cwd>/.johnston/skills/).
Supports YAML frontmatter parsing from SKILL.md and *.md files.
"""

import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from core.domain.defaults.git_excludes import DEFAULT_IGNORE_DIRS
from core.domain.defaults.skills.loader import BundledSkill, get_bundled_skill, list_bundled_skills
from core.infrastructure.platform.paths import CONFIG_DIR
from core.infrastructure.runtime.frontmatter import parse_frontmatter
from core.infrastructure.runtime.fs_signature import compute_dir_signature_recursive

logger = logging.getLogger(__name__)

GLOBAL_SKILLS_DIR = os.path.join(CONFIG_DIR, "skills")
PROJECT_SKILLS_DIR_NAME = os.path.join(".johnston", "skills")


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
    _dirs_ensured: bool = False

    _CACHE_TTL = 2.0  # seconds

    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_dir = GLOBAL_SKILLS_DIR
        self.project_dir_skills = os.path.join(self.project_dir, PROJECT_SKILLS_DIR_NAME)
        self._scan_signature: Optional[tuple] = None
        self._scan_cache: Optional[List[Skill]] = None
        self._scan_ts: float = 0.0
        if not SkillManager._dirs_ensured:
            self.ensure_dirs()
            SkillManager._dirs_ensured = True

    def ensure_dirs(self):
        os.makedirs(self.global_dir, exist_ok=True)
        from core.infrastructure.platform.platform_utils import atomic_write_text

        # Provision bundled default skills (init, handoff, johnston-guide) into
        # the user's global skills dir. Each skill is a directory with SKILL.md
        # and optional extra files. Existing files are left untouched so users
        # can edit/remove their local copies.
        for name in list_bundled_skills():
            self._provision_skill(get_bundled_skill(name), atomic_write_text)

    def _provision_skill(self, skill: BundledSkill, write_func):
        """Write a bundled skill's files into the global skills dir if missing."""
        skill_dir = os.path.join(self.global_dir, skill.name)
        for rel_path, content in skill.files.items():
            target_path = os.path.join(skill_dir, rel_path)
            if os.path.exists(target_path):
                continue
            try:
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                write_func(target_path, content)
            except Exception:
                logger.warning("Failed to write skill file: %s", target_path, exc_info=True)

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
                    continue

                fm, body = parse_frontmatter(raw_content)

                name = fm.get("name")
                if not name:
                    if os.path.basename(filepath) == "SKILL.md":
                        name = os.path.basename(os.path.dirname(filepath))
                    else:
                        name = os.path.splitext(os.path.basename(filepath))[0]

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

                hidden_val = str(fm.get("hidden", "")).lower()
                user_invocable_val = str(fm.get("user_invocable", "")).lower()

                is_hidden = hidden_val in ("true", "1", "yes") or user_invocable_val in ("false", "0", "no")

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
        Returns True if now hidden, False if visible.
        """
        skill = self.get_skill(name, include_hidden=True)
        if not skill or not skill.location:
            return False

        filepath = skill.location
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            is_currently_hidden = skill.hidden
            new_hidden = not is_currently_hidden

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
                        elif sline.startswith("user_invocable:"):
                            new_fm_lines.append(f"user_invocable: {str(not new_hidden).lower()}")
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

            from core.infrastructure.platform.platform_utils import atomic_write_text

            atomic_write_text(filepath, new_content)
            self.invalidate_cache()

            return new_hidden
        except Exception:
            return skill.hidden

    def get_system_prompt_skills(self) -> List[Skill]:
        """Return non-hidden skills for the system prompt.

        Data-only: leaves Markdown bullet assembly to the prompt builder so this
        application module does not own rendering output.
        """
        return self.list_skills(include_hidden=False, for_system_prompt=True)
