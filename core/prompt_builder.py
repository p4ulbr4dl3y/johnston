import datetime
import os
import platform
import subprocess
from typing import Any, Dict, List

from core.skill_manager import SkillManager
from tools.subagent import SubagentTool


def get_git_info() -> str:
    """Returns current git branch and dirty working tree status safely."""
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "-s"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1
        ).strip()
        lines = [line for line in status.splitlines() if line.strip()]
        dirty_summary = f"{len(lines)} modified/untracked file(s)" if lines else "clean working tree"
        if branch:
            return f"branch '{branch}' ({dirty_summary})"
        elif lines:
            return f"detached HEAD ({dirty_summary})"
    except Exception:
        pass
    return ""


def get_project_instructions_snippet() -> str:
    """Reads AGENTS.md, CLAUDE.md, .cursorrules, .windsurfrules, or CONVENTIONS.md from current working directory."""
    cwd = os.getcwd()
    candidates = ["AGENTS.md", "CLAUDE.md", ".cursorrules", ".windsurfrules", "CONVENTIONS.md"]
    found_snippets = []

    for name in candidates:
        filepath = os.path.join(cwd, name)
        if os.path.isfile(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                if content:
                    if len(content) > 6000:
                        content = content[:6000] + "\n... [Project instructions truncated at 6000 chars]"
                    found_snippets.append(f"[PROJECT INSTRUCTIONS ({name})]:\n{content}")
            except Exception:
                pass

    return "\n\n".join(found_snippets)


def get_rules_snippet(mode: str = "action") -> str:
    """Reads rules from ~/.johnston/rules, <cwd>/.johnston/rules, and <cwd>/.rules using RulesManager."""
    from core.rules_manager import RulesManager
    return RulesManager.get_instance().get_formatted_rules(mode=mode)


DEFAULT_SYSTEM_PROMPT = """You are Johnston, an expert AI software engineer pair programming with the user.

Core Principles:
1. Research First: Inspect the codebase using list_dir, glob, and grep before forming hypotheses or making changes. Never guess file paths, signatures, or implementations.
2. Read Before Edit: Always read target file contents with read before making modifications with edit or create.
3. Verification: Execute verification commands, linting, or unit tests via bash to verify your code changes work cleanly before concluding.
4. Precision Edits: When using edit, include enough surrounding context lines and match exact indentation. Mimic existing project code conventions and style.
5. Minimal Code Comments: Do NOT add unnecessary code comments unless explicitly requested by the user.
6. No Unsolicited Commits: NEVER execute git commits unless explicitly instructed by the user.
7. Clarification: Use ask_user to ask questions when user intent or design requirements are ambiguous.
8. Subagents: Use subagent to launch autonomous subagents for multi-step research or codebase exploration.
9. Background CLI Tasks: Use manage_task to monitor, check status, or terminate background shell commands.
10. Concise Communication: Be direct, clear, and concise (under 4 lines of text outside code/tools). Avoid unnecessary preamble or post-task explanations.
11. Dynamic & MCP Tools: You have access to all tools provided in your function definitions (including MCP and Skill tools). Always use available tool functions directly when applicable and do not claim tools are missing if they are in your tool list.
12. Language Matching: Always respond in the language used by the user in their current message unless explicitly requested otherwise."""


class PromptBuilder:
    """Builds composite system prompt and tool definitions accounting for MCP, Skills, and mode (Action/Explore)"""

    def __init__(self, base_system_prompt: str, base_tools: List[Dict[str, Any]], mode: str = "action", allow_task: bool = True):
        self.base_system_prompt = base_system_prompt
        self.base_tools = list(base_tools or [])
        self.mode = mode
        self.allow_task = allow_task

    def build_system_prompt(self) -> str:
        from core.mcp_manager import get_mcp_manager
        mcp_mgr = get_mcp_manager()
        mcp_snippet = mcp_mgr.get_system_prompt_snippet()
        skills_snippet = SkillManager().get_system_prompt_snippet()

        now_str = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        os_info = f"{platform.system()} {platform.release()}"
        git_info = get_git_info()

        env_lines = [
            "Environment Metadata:",
            f"- Working Directory: {os.getcwd()}",
            f"- Local Time: {now_str}",
            f"- Operating System: {os_info}"
        ]
        if git_info:
            env_lines.append(f"- Git Context: {git_info}")

        env_block = "\n".join(env_lines)

        project_snippet = get_project_instructions_snippet()
        rules_snippet = get_rules_snippet(mode=self.mode)

        sys_prompt = f"{self.base_system_prompt}\n\n{env_block}"
        if project_snippet:
            sys_prompt = f"{sys_prompt}\n\n{project_snippet}"
        if rules_snippet:
            sys_prompt = f"{sys_prompt}\n\n[USER RULES]\n{rules_snippet}"
        if skills_snippet:
            sys_prompt = f"{sys_prompt}\n\n{skills_snippet}"
        if mcp_snippet:
            sys_prompt = f"{sys_prompt}\n\n{mcp_snippet}"

        mode_lower = self.mode.lower()
        if mode_lower in ("explore", "plan", "ask"):
            sys_prompt += (
                "\n\n[MODE: EXPLORE]\n"
                "Read-only research, codebase inspection, QA, and plan drafting.\n"
                "Rules:\n"
                "1. Code modification tools (create, edit) are disabled.\n"
                "2. Output findings/plan directly in chat (Goal, Proposed Changes, Verification).\n"
                "3. Ask the user to switch to Action mode (via Shift+Tab or /action) when ready to apply changes."
            )
        else:
            local_plan = os.path.join(os.getcwd(), ".johnston", "plans", "plan.md")
            plan_note = f" Refer to plan at '{local_plan}' if present." if os.path.exists(local_plan) else ""
            sys_prompt += (
                f"\n\n[MODE: ACTION]\n"
                f"Execution and implementation mode. Write, edit, bash, and task tools are fully enabled.{plan_note}\n"
                "Execute tasks precisely, write clean code, and verify with tests."
            )

        return sys_prompt

    def build_tools(self, provider_key: str = "", model_id: str = "") -> List[Dict[str, Any]]:
        from core.mcp_manager import get_mcp_manager
        from core.models_catalog import catalog

        mcp_tools = get_mcp_manager().get_active_tools()
        clean_mcp_tools = [
            {"type": t["type"], "function": t["function"]} for t in mcp_tools
        ]

        all_tools = list(self.base_tools) + clean_mcp_tools

        mode_lower = self.mode.lower()
        if mode_lower in ("explore", "plan", "ask"):
            # Filter out file modification tools in explore mode
            all_tools = [
                t for t in all_tools
                if t.get("function", {}).get("name") not in ("create", "edit", "Create", "Edit")
            ]

        if self.allow_task and not any(t.get("function", {}).get("name") in ("subagent", "Subagent", "Task", "task") for t in all_tools):
            all_tools.append(SubagentTool.schema)

        if provider_key and model_id and not catalog.supports_vision(provider_key, model_id):
            updated_tools = []
            for t in all_tools:
                t_func = t.get("function", {})
                if t_func.get("name") in ("view_image", "ViewImage"):
                    t = {
                        "type": "function",
                        "function": {
                            "name": "view_image",
                            "description": "Inspect an image file on disk via Vision Sub-Agent. Provide image path and detailed prompt.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string", "description": "Absolute or relative path to image file"},
                                    "prompt": {"type": "string", "description": "Prompt for Vision Sub-Agent describing what to inspect in the image"}
                                },
                                "required": ["path", "prompt"]
                            }
                        }
                    }
                updated_tools.append(t)
            all_tools = updated_tools

        return all_tools
