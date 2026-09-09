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
from typing import Dict, List, Optional

from johnston.core.domain.defaults.git_excludes import DEFAULT_IGNORE_DIRS
from johnston.core.domain.defaults.skills.loader import load_bundled_skills
from johnston.core.domain.entities.skills import Skill, SkillScope
from johnston.core.infrastructure.config.settings import SkillsSettings, get_settings, patch_settings
from johnston.core.infrastructure.platform.paths import CONFIG_DIR
from johnston.core.infrastructure.runtime.frontmatter import parse_frontmatter
from johnston.core.infrastructure.runtime.fs_signature import compute_dir_signature_recursive

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


class SkillManager:
    """Discovers skills in the global and project trees with signature-based caching.

    Construction is side-effect free; use :func:`get_skill_manager` to obtain the
    shared, provisioning instance.
    """

    _CACHE_TTL = 2.0  # seconds

    def __init__(self, project_dir: Optional[str] = None, include_bundled: bool = True):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_dir = GLOBAL_SKILLS_DIR
        self.project_dir_skills = os.path.join(self.project_dir, PROJECT_SKILLS_DIR_NAME)
        self.include_bundled = include_bundled
        self._scan_signature: Optional[tuple] = None
        self._scan_cache: Optional[List[Skill]] = None
        self._scan_ts: float = 0.0
        # Cache of parsed (Skill, mtime_ns, size) keyed by filepath so file contents
        # are only read/parsed once unless the file itself changed.
        self._parsed_file_cache: Dict[str, tuple[Skill, int, int]] = {}

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
        try:
            hidden_sig = tuple(sorted(get_settings().skills.hidden.items()))
        except Exception:
            hidden_sig = ()
        return (tuple(entries), hidden_sig)

    def _scan_skills(self) -> tuple:
        """Scans bundled, global and project skills, returning (skills, signature).
        Project skills override global skills, which in turn override bundled skills.
        """
        skills_map: Dict[str, Skill] = {}
        signature_entries: List[tuple] = []
        real_global = os.path.realpath(self.global_dir)
        real_project = os.path.realpath(self.project_dir_skills)

        # 1. Base layer: bundled skills directly from package data
        if self.include_bundled:
            for b_skill in load_bundled_skills():
                skills_map[b_skill.name.lower()] = b_skill

        # 2. Overlays: Global then Project
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

            parsed_cache = getattr(self, "_parsed_file_cache", None)
            if parsed_cache is None:
                parsed_cache = {}
                self._parsed_file_cache = parsed_cache

            for filepath in sorted(md_files):
                try:
                    st = os.stat(filepath)
                    mtime_ns, size = st.st_mtime_ns, st.st_size
                except OSError:
                    mtime_ns, size = 0, 0

                cached_entry = parsed_cache.get(filepath)
                if cached_entry and cached_entry[1] == mtime_ns and cached_entry[2] == size:
                    skill = cached_entry[0]
                    skills_map[skill.name.lower()] = skill
                    continue

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

                skill = Skill(
                    name=name,
                    description=desc,
                    location=filepath,
                    content=body.strip(),
                    scope=SkillScope(scope),
                    hidden=is_hidden,
                )
                parsed_cache[filepath] = (skill, mtime_ns, size)
                skills_map[name.lower()] = skill

        # 3. Apply hidden status overrides from settings without mutating cached instances
        try:
            hidden_overrides = get_settings().skills.hidden
            for name_lower, skill in list(skills_map.items()):
                override = hidden_overrides.get(name_lower)
                if override is not None and skill.hidden != bool(override):
                    skills_map[name_lower] = Skill(
                        name=skill.name,
                        description=skill.description,
                        location=skill.location,
                        content=skill.content,
                        scope=skill.scope,
                        hidden=bool(override),
                    )
        except Exception:
            logger.debug("Failed to apply skills.hidden settings override", exc_info=True)

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
        """Toggles the 'hidden' attribute of a skill in user settings (config.json).

        Returns the new hidden state (True = hidden, False = visible).
        Raises KeyError for an unknown skill.
        """
        skill = self.get_skill(name, include_hidden=True)
        if not skill:
            raise KeyError(f"Unknown skill: {name!r}")

        new_hidden = not skill.hidden
        try:
            settings = get_settings()
            current_dict = dict(settings.skills.hidden)
            current_dict[skill.name.lower()] = new_hidden
            patch_settings(skills=SkillsSettings(hidden=current_dict))
            self.invalidate_cache()
            return new_hidden
        except Exception:
            logger.warning("Failed to toggle hidden in settings for skill %r", name, exc_info=True)
            raise

    def get_system_prompt_skills(self) -> List[Skill]:
        """Return non-hidden skills for the system prompt.

        Data-only: leaves Markdown bullet assembly to the prompt builder so this
        application module does not own rendering output.
        """
        return self.list_skills(include_hidden=False, for_system_prompt=True)


# Shared per-process managers keyed by resolved project dir, so every consumer
# (UI screens, command providers, prompt builder) shares one scan cache.
_SKILL_MANAGERS: Dict[tuple, SkillManager] = {}
_registry_lock = threading.Lock()


def get_skill_manager(project_dir: Optional[str] = None) -> SkillManager:
    """Return the shared SkillManager for ``project_dir`` (defaults to cwd).

    Managers are cached by (resolved project dir, global skills dir) so that a
    change in configuration/global skills directory (e.g. per-test isolation)
    yields a fresh manager instead of reusing one that scans a stale directory.
    """
    key = (
        os.path.realpath(project_dir or os.getcwd()),
        os.path.realpath(GLOBAL_SKILLS_DIR),
    )
    with _registry_lock:
        mgr = _SKILL_MANAGERS.get(key)
        if mgr is None:
            mgr = SkillManager(project_dir=key[0])
            _SKILL_MANAGERS[key] = mgr
        return mgr

