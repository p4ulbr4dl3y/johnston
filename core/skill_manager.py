"""
Skill Manager for Johnston.
Handles global skills (~/.johnston/skills/) and project-level skills (<cwd>/.johnston/skills/).
Supports YAML frontmatter parsing from SKILL.md and *.md files.
"""
import os
from typing import Any, Dict, List, Optional, Tuple

from core.config import CONFIG_DIR

GLOBAL_SKILLS_DIR = os.path.join(CONFIG_DIR, "skills")
PROJECT_SKILLS_DIR_NAME = os.path.join(".johnston", "skills")

def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    Parses YAML frontmatter delimited by `---`.
    Returns (frontmatter_dict, body_content).
    """
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2]
            fm = {}
            for line in fm_text.splitlines():
                line = line.strip()
                if line and ":" in line and not line.startswith("#"):
                    k, v = line.split(":", 1)
                    fm[k.strip().lower()] = v.strip().strip('"').strip("'")
            return fm, body
    return {}, content

class SkillManager:
    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_dir = GLOBAL_SKILLS_DIR
        self.project_dir_skills = os.path.join(self.project_dir, PROJECT_SKILLS_DIR_NAME)
        self.ensure_dirs()

    def ensure_dirs(self):
        os.makedirs(self.global_dir, exist_ok=True)
        os.makedirs(self.project_dir_skills, exist_ok=True)

    def list_skills(self) -> List[Dict[str, Any]]:
        """
        Discovers skills in global and project directories.
        Project skills override global skills with the same name.
        """
        skills_map: Dict[str, Dict[str, Any]] = {}

        for scope, dir_path in [("global", self.global_dir), ("project", self.project_dir_skills)]:
            if not os.path.exists(dir_path):
                continue

            md_files = []
            for root, _, files in os.walk(dir_path):
                for f in files:
                    if f.endswith(".md"):
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
                    lines = [line.strip("# ").strip() for line in body.splitlines() if line.strip() and not line.startswith("#")]
                    desc = lines[0] if lines else ""

                skills_map[name] = {
                    "name": name,
                    "description": desc,
                    "location": filepath,
                    "directory": rel_dir,
                    "content": body.strip(),
                    "scope": scope,
                }

        return list(skills_map.values())

    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        skills = self.list_skills()
        for s in skills:
            if s["name"].lower() == name.lower():
                return s
        return None

    def load_skill_payload(self, name: str, file_limit: int = 10) -> str:
        skill = self.get_skill(name)
        if not skill:
            return f"Error: Unable to load skill '{name}'"

        skill_dir = skill["directory"]
        is_skill_md = os.path.basename(skill["location"]) == "SKILL.md"

        sampled_files = []
        if is_skill_md and os.path.exists(skill_dir):
            for root, _, files in os.walk(skill_dir):
                for f in sorted(files):
                    if f == "SKILL.md" or f.startswith("."):
                        continue
                    full_p = os.path.join(root, f)
                    rel_p = os.path.relpath(full_p, skill_dir)
                    sampled_files.append(rel_p)
                    if len(sampled_files) >= file_limit:
                        break
                if len(sampled_files) >= file_limit:
                    break

        files_xml = ""
        if sampled_files:
            files_list_str = "\n".join(f"  <file>{f}</file>" for f in sampled_files)
            files_xml = f"\n<skill_files>\n{files_list_str}\n</skill_files>"

        return (
            f'<skill_content name="{skill["name"]}">\n'
            f'# Skill: {skill["name"]}\n\n'
            f'{skill["content"]}\n\n'
            f'Base directory for this skill: {skill_dir}\n'
            f'Relative paths in this skill are relative to this base directory.'
            f'{files_xml}\n'
            f'</skill_content>'
        )

    def get_system_prompt_snippet(self) -> str:
        skills = self.list_skills()
        if not skills:
            return ""
        lines = ["Available skills in system context:"]
        for s in skills:
            desc = f" - {s['description']}" if s['description'] else ""
            lines.append(f"- {s['name']} ({s['scope']}){desc}")
        return "\n".join(lines)
