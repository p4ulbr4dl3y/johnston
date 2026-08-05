"""
Skill Manager for Johnston.
Handles global skills (~/.johnston/skills/) and project-level skills (<cwd>/.johnston/skills/).
Supports YAML frontmatter parsing from SKILL.md and *.md files.
"""
import os
from typing import Any, Dict, List, Optional, Tuple

from core.config import CONFIG_DIR, DEFAULT_IGNORE_DIRS

GLOBAL_SKILLS_DIR = os.path.join(CONFIG_DIR, "skills")
PROJECT_SKILLS_DIR_NAME = os.path.join(".johnston", "skills")

def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    Parses YAML frontmatter delimited by `---`.
    Supports single-line and multi-line scalar values (including > and | block scalars).
    Returns (frontmatter_dict, body_content).
    """
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2]
            fm: Dict[str, Any] = {}
            current_key = None
            current_val_lines = []

            def _flush():
                nonlocal current_key, current_val_lines
                if current_key:
                    joined = " ".join(line_item.strip() for line_item in current_val_lines if line_item.strip()).strip()
                    if joined in (">", "|"):
                        joined = ""
                    elif joined.startswith("> ") or joined.startswith("| "):
                        joined = joined[2:].strip()
                    elif (joined.startswith(">") or joined.startswith("|")) and len(joined) > 1:
                        joined = joined[1:].strip()
                    fm[current_key] = joined.strip('"').strip("'")
                current_key = None
                current_val_lines = []

            for line in fm_text.splitlines():
                sline = line.strip()
                if not sline or sline.startswith("#"):
                    continue

                if ":" in sline and not line.startswith(" ") and not line.startswith("\t"):
                    _flush()
                    k, v = sline.split(":", 1)
                    current_key = k.strip().lower()
                    v_str = v.strip().strip('"').strip("'")
                    current_val_lines = [v_str] if v_str else []
                elif current_key and (line.startswith(" ") or line.startswith("\t")):
                    current_val_lines.append(sline)

            _flush()
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
- Location: `~/.johnston/modes/<name>.md` (global) or `.johnston/modes/<name>.md` (project).
- Format: Markdown with YAML frontmatter:
  ```markdown
  ---
  name: Architect
  description: High-level design mode
  read_only: true
  disallowed_tools: create, edit
  ---
  Custom system prompt here...
  ```
- Verification: Run `johnston --modes` via shell tool.
"""

DEFAULT_INIT_SKILL_CONTENT = """---
name: init
description: Guided AGENTS.md project setup
---

# Repository Initialization

## Goal
Create or update `AGENTS.md` for this repository to help future AI sessions avoid mistakes and ramp up quickly.

## Investigation Protocol
Read high-value sources first:
1. `README*`, root manifests, workspace config, lockfiles
2. Build, test, lint, formatter, typecheck, and codegen config
3. CI workflows and pre-commit / task runner config
4. Existing instruction files (`AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, `.cursorrules`)

If architecture is still unclear, inspect representative code files to find entrypoints and boundaries.

## Writing Rules
Include high-signal, repo-specific guidance:
1. Exact commands and shortcuts the agent would otherwise guess wrong
2. Architecture notes not obvious from filenames
3. Conventions that differ from language or framework defaults

When in doubt, omit. Prefer short sections and bullets.
If `AGENTS.md` already exists, improve it in place rather than rewriting blindly."""

DEFAULT_HANDOFF_SKILL_CONTENT = """---
name: handoff
description: Prepare a continuation note for the next AI session
---

# Session Continuation Handoff Note

## Goal
Create or update `HANDOFF.md` in the repository working directory to enable another AI agent to continue work seamlessly.

## Execution Constraints & Security
1. Do not output the full handoff note in chat. Write or overwrite `HANDOFF.md` using file tools.
2. Output only a brief 1-2 sentence confirmation linking to `HANDOFF.md` in chat.
3. REDACT all sensitive information, including API keys, tokens, passwords, and personally identifiable information (PII).
4. DO NOT infer or hallucinate completed work, decisions, inspected files, or test results not present in the conversation context.

## Required Document Structure (`HANDOFF.md`)
1. **Goal & User Intent**: High-level goal, current objective, and explicit user requirements.
2. **Current State & Modified Files**: Work completed so far. Reference key modified/created files using exact paths (e.g. `path/file.ext#L10-L30`).
3. **Decisions Made (Do Not Re-litigate)**: Architectural/technical choices agreed upon and the rationale behind them.
4. **Verification & Test Status**: Explicit commands run (e.g. `uv run pytest`) and their exact results (PASS/FAIL).
5. **Remaining Tasks & Open Questions**: Actionable next steps, unresolved questions, or blockers.
6. **Active / Recommended Skills & Tools**: Skills or tools used in this session or recommended for the next session.

## Writing Rules
1. If there is little or no prior session context, state that explicitly in the file.
2. Prefer concise sections and bullet points.
3. Do not dump entire source files or raw conversation logs into `HANDOFF.md`. Use file links for existing code. You MAY write detailed Markdown explanations, architectural specs, or essential code snippets if crucial for continuation."""


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

        default_skills = [
            ("johnston-architect", DEFAULT_ARCHITECT_SKILL_CONTENT, "Custom Execution Modes"),
            ("init", DEFAULT_INIT_SKILL_CONTENT, "Repository Initialization"),
            ("handoff", DEFAULT_HANDOFF_SKILL_CONTENT, "Session Continuation Handoff Note"),
        ]

        from tools.base import atomic_write_text

        for skill_name, skill_content, check_marker in default_skills:
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

            from tools.base import atomic_write_text
            atomic_write_text(filepath, new_content)

            return new_hidden
        except Exception:
            return skill.get("hidden", False)

    def load_skill_payload(self, name: str, file_limit: int = 10) -> str:
        skill = self.get_skill(name)
        if not skill:
            return f"Error: Unable to load skill '{name}'"

        skill_dir = skill["directory"]
        is_skill_md = os.path.basename(skill["location"]) == "SKILL.md"

        sampled_files = []
        if is_skill_md and os.path.exists(skill_dir):
            for root, dirs, files in os.walk(skill_dir):
                dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]
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
        skills = self.list_skills(include_hidden=False, for_system_prompt=True)
        if not skills:
            return ""

        global_skills = []
        project_skills = []

        for s in skills:
            desc = f": {s['description']}" if s['description'] else ""
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


