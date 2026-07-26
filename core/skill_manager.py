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

DEFAULT_ARCHITECT_SKILL_CONTENT = """---
name: johnston-architect
description: Johnston system configurator & architect. Manages MCP servers, subagent definitions, rules, LLM providers, and skills with CLI self-verification.
---

# Johnston Architect Skill

You are the Johnston System Configurator & Architect. Your goal is to configure, customize, and extend Johnston safely according to user requests.

## Core Capabilities & Instructions

### 1. MCP Server Configuration (`johnston --mcp`)
- Location: `~/.johnston/mcp.json` (global) or `.johnston/mcp.json` (project).
- Format: JSON object containing server configurations (command, args, env, disabled).
- Verification: Run `johnston --mcp` via shell tool to verify server registration.

### 2. Custom Subagent Definitions (`johnston --subagents`)
- Location: `~/.johnston/subagents/definitions/<name>.md` (global) or `.johnston/subagents/<name>.md` (project).
- Format: Markdown with YAML frontmatter:
  ```markdown
  ---
  name: reviewer
  description: Code reviewer subagent
  tools: read, grep, glob
  model: deepseek-v4-flash
  ---
  System prompt instructions here...
  ```
- Verification: Run `johnston --subagents` via shell tool.

### 3. Rules & Instructions (`johnston --rules`)
- Location: `~/.johnston/rules/<name>.md` (global) or `.johnston/rules/<name>.md` (project).
- Format: Markdown with optional YAML frontmatter:
  ```markdown
  ---
  name: python_style
  mode: action, explore
  globs: "*.py"
  ---
  Rule instructions here...
  ```
- Verification: Run `johnston --rules` via shell tool.

### 4. LLM Providers Setup (`johnston --models`)
- Location: `~/.johnston/providers.json`.
- Format: JSON object for OpenAI, Anthropic, Gemini, or Ollama endpoints:
  ```json
  "my_llm": {
    "key": "my_llm",
    "name": "Custom LLM",
    "base_url": "https://api.myllm.com/v1",
    "model": "model-v1",
    "api_type": "openai",
    "models": ["model-v1", "model-v2"],
    "fetch_models": false
  }
  ```
- Verification: Run `johnston --models` via shell tool.

### 5. Skills Management (`johnston --skills`)
- Location: `~/.johnston/skills/<name>/SKILL.md` (global) or `.johnston/skills/<name>/SKILL.md` (project).
- Verification: Run `johnston --skills` via shell tool.

### 6. Custom Execution Modes (`johnston --modes`)
- Location: `~/.johnston/modes/<name>.json` or `.md` (global) or `.johnston/modes/<name>.json` or `.md` (project).
- Format: JSON object or Markdown with YAML frontmatter:
  ```json
  {
    "key": "architect",
    "name": "Architect",
    "description": "High-level design mode",
    "read_only": true,
    "prompt": "Custom system prompt...",
    "disallowed_tools": ["create", "edit"]
  }
  ```
- Verification: Run `johnston --modes` via shell tool.
"""


class SkillManager:
    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_dir = GLOBAL_SKILLS_DIR
        self.project_dir_skills = os.path.join(self.project_dir, PROJECT_SKILLS_DIR_NAME)
        self.ensure_dirs()

    def ensure_dirs(self):
        os.makedirs(self.global_dir, exist_ok=True)
        os.makedirs(self.project_dir_skills, exist_ok=True)

        architect_dir = os.path.join(self.global_dir, "johnston-architect")
        architect_file = os.path.join(architect_dir, "SKILL.md")
        should_write = False
        if not os.path.exists(architect_file):
            should_write = True
        else:
            try:
                with open(architect_file, "r", encoding="utf-8") as f:
                    content = f.read()
                if "Custom Execution Modes" not in content:
                    should_write = True
            except Exception:
                should_write = True

        if should_write:
            try:
                os.makedirs(architect_dir, exist_ok=True)
                with open(architect_file, "w", encoding="utf-8") as f:
                    f.write(DEFAULT_ARCHITECT_SKILL_CONTENT.strip())
            except Exception:
                pass

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
