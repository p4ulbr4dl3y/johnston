import datetime
import os
import platform
import subprocess
from typing import Any, Dict, List

from core.skill_manager import SkillManager
from tools.plan_exit import PlanExitTool
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
    """Reads AGENTS.md, CLAUDE.md, or .cursorrules from current working directory if available."""
    cwd = os.getcwd()
    candidates = ["AGENTS.md", "CLAUDE.md", ".cursorrules", "CONVENTIONS.md"]
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


DEFAULT_SYSTEM_PROMPT = """You are Johnston, an expert AI software engineer pair programming with the user.

Core Principles:
1. Research First: Inspect the codebase using ListDir, Glob, and Grep before forming hypotheses or making changes. Never guess file paths, signatures, or implementations.
2. Read Before Edit: Always read target file contents with Read before making modifications with Edit or Create.
3. Verification: Execute verification commands or tests via Bash to verify your code changes work cleanly before concluding.
4. Precision Edits: When using Edit, include enough surrounding context lines and match exact indentation.
5. Clarification: Use AskUser to ask questions when user intent or design requirements are ambiguous.
6. Subagents: Use Subagent to launch autonomous subagents for multi-step research or codebase exploration.
7. Background CLI Tasks: Use ManageTask to monitor, check status, or terminate background shell commands.
8. Concise Communication: Be direct, clear, and concise. Avoid unnecessary preamble.
9. Dynamic & MCP Tools: You have access to all tools provided in your function definitions (including MCP and Skill tools). Always use available tool functions directly when applicable and do not claim tools are missing if they are in your tool list."""


class PromptBuilder:
    """Формирует скомпонованный системный промпт и набор инструментов с учетом MCP, Skills и режима (Plan/Build)"""

    def __init__(self, base_system_prompt: str, base_tools: List[Dict[str, Any]], mode: str = "build", allow_task: bool = True):
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

        sys_prompt = f"{self.base_system_prompt}\n\n{env_block}"
        if project_snippet:
            sys_prompt = f"{sys_prompt}\n\n{project_snippet}"
        if skills_snippet:
            sys_prompt = f"{sys_prompt}\n\n{skills_snippet}"
        if mcp_snippet:
            sys_prompt = f"{sys_prompt}\n\n{mcp_snippet}"

        mode_lower = self.mode.lower()
        if mode_lower == "plan":
            sys_prompt += (
                "\n\n[PLAN MODE ACTIVE]\n"
                "You are in Plan mode. Analyze the codebase, research requirements, and design a step-by-step implementation plan.\n"
                "Guidelines:\n"
                "1. Perform read-only codebase exploration using Read, ListDir, Glob, Grep.\n"
                "2. Output your complete, detailed implementation plan DIRECTLY in your chat response text. Do NOT attempt to create or edit files on disk.\n"
                "3. Your plan should clearly cover: Goal, Proposed File Changes, and Verification Steps.\n"
                "4. Present your plan and ask the user to confirm. Call the PlanExit tool AFTER the user approves the plan (or tells you to proceed) to switch to Build mode for execution."
            )
        elif mode_lower == "ask":
            sys_prompt += (
                "\n\n[ASK MODE ACTIVE - READ-ONLY ASSISTANT]\n"
                "You are in Ask mode — a read-only assistant focused on answering questions and explaining concepts without modifying the codebase.\n"
                "Guidelines:\n"
                "1. Answer questions thoroughly with clear explanations, code context, and Mermaid diagrams where helpful.\n"
                "2. Perform read-only exploration using Read, ListDir, Glob, Grep, etc.\n"
                "3. Do NOT modify files or run write commands. Your toolset is read-only.\n"
                "4. If a task requires code edits or file creation, suggest switching to /build or /code mode."
            )
        elif mode_lower == "debug":
            sys_prompt += (
                "\n\n[DEBUG MODE ACTIVE - SYSTEMATIC DEBUGGER]\n"
                "You are in Debug mode — an expert software debugger specializing in systematic problem diagnosis.\n"
                "Guidelines:\n"
                "1. Reflect on 5-7 different potential sources of the issue.\n"
                "2. Distill those down to 1-2 most probable root causes based on empirical evidence.\n"
                "3. Add logging or run diagnostic commands via Bash to validate your assumptions before making fixes.\n"
                "4. Explicitly ask the user via AskUser or message to confirm diagnosis before applying a fix.\n"
                "5. Prefer minimal, targeted fixes over broad refactors."
            )
        elif mode_lower == "orchestrator":
            sys_prompt += (
                "\n\n[ORCHESTRATOR MODE ACTIVE - WORKFLOW COORDINATOR]\n"
                "You are in Orchestrator mode — a strategic workflow coordinator who breaks down complex tasks into subtask waves.\n"
                "Guidelines:\n"
                "1. Research codebase first to identify files, patterns, and dependencies.\n"
                "2. Classify subtasks into parallel execution waves (subtasks touching different files can run in parallel).\n"
                "3. Delegate execution wave-by-wave using the Subagent tool.\n"
                "4. Do NOT edit files directly yourself — delegate all implementation to subagents.\n"
                "5. Synthesize final results when all waves complete."
            )
        else:
            local_plan = os.path.join(os.getcwd(), ".johnston", "plans", "plan.md")
            if os.path.exists(local_plan):
                sys_prompt += f"\n\n[BUILD MODE ACTIVE]\nA plan file exists at '{local_plan}'. Execute the implementation steps defined within it."
            else:
                sys_prompt += "\n\n[BUILD MODE ACTIVE]\nYou are in Build mode. You have full access to create/edit files and run commands."

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
        if mode_lower in ("ask", "plan"):
            # Filter out file modification tools in ask and plan modes
            all_tools = [
                t for t in all_tools
                if t.get("function", {}).get("name") not in ("Create", "Edit")
            ]

        if mode_lower == "plan":
            if not any(t.get("function", {}).get("name") == "PlanExit" for t in all_tools):
                all_tools.append(PlanExitTool.schema)

        if self.allow_task and not any(t.get("function", {}).get("name") in ("Subagent", "Task", "task") for t in all_tools):
            all_tools.append(SubagentTool.schema)

        if provider_key and model_id and not catalog.supports_vision(provider_key, model_id):
            updated_tools = []
            for t in all_tools:
                t_func = t.get("function", {})
                if t_func.get("name") == "ViewImage":
                    t = {
                        "type": "function",
                        "function": {
                            "name": "ViewImage",
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
