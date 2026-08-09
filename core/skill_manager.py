"""
Skill Manager for Johnston.
Handles global skills (~/.johnston/skills/) and project-level skills (<cwd>/.johnston/skills/).
Supports YAML frontmatter parsing from SKILL.md and *.md files.
"""

import os
from typing import Any, Dict, List, Optional

from core.config import CONFIG_DIR
from core.defaults.config import DEFAULT_IGNORE_DIRS
from core.defaults.skills.handoff_skill import DEFAULT_HANDOFF_SKILL_CONTENT
from core.defaults.skills.init_skill import DEFAULT_INIT_SKILL_CONTENT
from core.defaults.skills.johnston_guide import JOHNSTON_GUIDE_FILES
from core.frontmatter import parse_frontmatter

GLOBAL_SKILLS_DIR = os.path.join(CONFIG_DIR, "skills")
PROJECT_SKILLS_DIR_NAME = os.path.join(".johnston", "skills")


class SkillManager:
    _dirs_ensured: bool = False

    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_dir = GLOBAL_SKILLS_DIR
        self.project_dir_skills = os.path.join(self.project_dir, PROJECT_SKILLS_DIR_NAME)
        if not SkillManager._dirs_ensured:
            self.ensure_dirs()
            SkillManager._dirs_ensured = True

    def ensure_dirs(self):
        os.makedirs(self.global_dir, exist_ok=True)
        from core.platform_utils import atomic_write_text

        # 1. Provision johnston-guide with references/
        guide_dir = os.path.join(self.global_dir, "johnston-guide")
        for rel_path, file_content in JOHNSTON_GUIDE_FILES.items():
            target_path = os.path.join(guide_dir, rel_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            if not os.path.exists(target_path):
                try:
                    atomic_write_text(target_path, file_content.strip())
                except Exception:
                    pass

        # 2. Single-file skills (init, handoff)
        single_skills = [
            ("init", DEFAULT_INIT_SKILL_CONTENT, "Repository Initialization"),
            ("handoff", DEFAULT_HANDOFF_SKILL_CONTENT, "Session Continuation Handoff Note"),
        ]

        for skill_name, skill_content, check_marker in single_skills:
            skill_dir = os.path.join(self.global_dir, skill_name)
            skill_file = os.path.join(skill_dir, "SKILL.md")
            should_write = False
            if not os.path.exists(skill_file):
                should_write = True
            else:
                try:
                    with open(skill_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    if check_marker and check_marker not in content:
                        should_write = True
                except Exception:
                    should_write = True

            if should_write:
                try:
                    os.makedirs(skill_dir, exist_ok=True)
                    atomic_write_text(skill_file, skill_content.strip())
                except Exception:
                    pass

    def list_skills(
        self,
        include_hidden: bool = True,
        for_system_prompt: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Discovers skills in global and project directories.
        Project skills override global skills with the same name.
        """
        skills_map: Dict[str, Dict[str, Any]] = {}
        real_global = os.path.realpath(self.global_dir)
        real_project = os.path.realpath(self.project_dir_skills)

        for scope, dir_path in [("global", self.global_dir), ("project", self.project_dir_skills)]:
            if scope == "project" and real_project == real_global:
                continue
            if not os.path.exists(dir_path):
                continue

            md_files = []
            for root, dirs, files in os.walk(dir_path):
                dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]
                for f in files:
                    if f == "SKILL.md":
                        md_files.append(os.path.join(root, f))

            for filepath in sorted(md_files):
                try:
                    with open(filepath, "r", encoding="utf-8") as file:
                        raw_content = file.read()
                except Exception:
                    continue

                fm, body = parse_frontmatter(raw_content)
                rel_dir = os.path.dirname(filepath)

                name = fm.get("name")
                if not name:
                    if os.path.basename(filepath) == "SKILL.md":
                        name = os.path.basename(rel_dir)
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

                skills_map[name] = {
                    "name": name,
                    "description": desc,
                    "location": filepath,
                    "directory": rel_dir,
                    "content": body.strip(),
                    "scope": scope,
                    "hidden": is_hidden,
                }

        skills = list(skills_map.values())
        result = []
        for s in skills:
            if for_system_prompt and s.get("hidden"):
                continue
            if not include_hidden and s.get("hidden"):
                continue
            result.append(s)
        return result

    def get_skill(self, name: str, include_hidden: bool = True) -> Optional[Dict[str, Any]]:
        skills = self.list_skills(include_hidden=include_hidden)
        for s in skills:
            if s["name"].lower() == name.lower():
                return s
        return None

    def toggle_hidden(self, name: str) -> bool:
        """
        Toggles the 'hidden' attribute of a skill in its frontmatter.
        Returns True if now hidden, False if visible.
        """
        skill = self.get_skill(name, include_hidden=True)
        if not skill or not skill.get("location"):
            return False

        filepath = skill["location"]
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            is_currently_hidden = skill.get("hidden", False)
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

            from core.platform_utils import atomic_write_text

            atomic_write_text(filepath, new_content)

            return new_hidden
        except Exception:
            return skill.get("hidden", False)

    def get_system_prompt_snippet(self) -> str:
        skills = self.list_skills(include_hidden=False, for_system_prompt=True)
        if not skills:
            return ""

        global_skills = []
        project_skills = []

        for s in skills:
            desc = f": {s['description']}" if s["description"] else ""
            line = f"- `{s['name']}`{desc}"
            if s.get("scope") == "project":
                project_skills.append(line)
            else:
                global_skills.append(line)

        lines = ["## Skills (read SKILL.md on user request or trigger)"]

        if global_skills:
            lines.append("\n### Global (`~/.johnston/skills/<name>/SKILL.md`)")
            lines.extend(global_skills)

        if project_skills:
            lines.append("\n### Project (`.johnston/skills/<name>/SKILL.md`)")
            lines.extend(project_skills)

        return "\n".join(lines)
