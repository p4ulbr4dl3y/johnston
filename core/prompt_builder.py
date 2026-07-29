import datetime
import os
import platform
import subprocess
import time
from typing import Any, Dict, List, Tuple

from core.skill_manager import SkillManager
from tools.subagent import SubagentTool

_GIT_INFO_CACHE: Dict[str, Any] = {"ts": 0.0, "val": ""}
_GIT_INFO_CACHE_TTL = 30.0


def get_git_info() -> str:
    """Returns current git branch and dirty working tree status safely.

    The result is cached briefly so the multi-step agent loop does not spawn two
    git subprocesses on every tool-call step. Freezing the git string within a
    turn also keeps the system prompt byte-identical across steps, which is what
    makes provider prompt caching (OpenAI auto-cache / Anthropic cache_control)
    actually hit on steps 2..N of a turn.
    """
    now = time.time()
    if now - _GIT_INFO_CACHE["ts"] < _GIT_INFO_CACHE_TTL:
        return _GIT_INFO_CACHE["val"]
    val = _compute_git_info()
    _GIT_INFO_CACHE["ts"] = now
    _GIT_INFO_CACHE["val"] = val
    return val


def _compute_git_info() -> str:
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
1. Research First: Inspect the codebase using shell commands (ls/find/dir, grep/rg/select-string) before forming hypotheses or making changes. Never guess file paths, signatures, or implementations.
2. Read Before Edit: Always read target file contents with read before making modifications.
3. Precision Edits: Prefer replace_file_content (with start_line/end_line ranges) for single contiguous edits and multi_replace_file_content for non-adjacent edits. Match exact indentation and existing project style.
4. Verification: Execute verification commands, linting, or unit tests via shell to verify your code changes work cleanly before concluding.
5. Minimal Code Comments: Do NOT add unnecessary code comments unless explicitly requested by the user.
6. No Unsolicited Commits: NEVER execute git commits unless explicitly instructed by the user.
7. Task Planning: For complex or multi-step tasks, use update_plan to maintain a step-by-step plan (steps 5-7 words, statuses: pending, in_progress, completed). Mark completed steps promptly.
8. Clarification: Use ask_user to ask questions when user intent or design requirements are ambiguous.
9. Subagents: Use subagent to launch autonomous subagents. Use workspace='branch' for isolated git worktree work.
10. Background Execution: When a command or subagent moves to the background, do not poll its status. You will be notified automatically upon completion. Either proceed with other useful tasks if needed, or update the user and end your turn to wait for notification.
11. Concise Communication: Be direct, clear, and concise. Do not repeat full plan contents after update_plan calls; summarize changes instead.
12. Dynamic & MCP Tools: You have access to all tools provided in your function definitions (including MCP and Skill tools). Always use available tool functions directly when applicable and do not claim tools are missing if they are in your tool list.
13. Language Matching: Always respond in the language used by the user in their current message unless explicitly requested otherwise.
14. Image Inspection: NEVER guess, describe, or summarize the contents of an image file (png, jpg, webp, gif, svg) without executing analyze_image on that file path. If you discover an image file via shell or list_dir, you MUST call analyze_image(path=...) to inspect its visual content before writing your answer."""


_SYSTEM_PROMPT_CACHE: Dict[tuple, Tuple[float, str]] = {}
_SYSTEM_PROMPT_CACHE_TTL = 30.0
_INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", ".cursorrules", ".windsurfrules", "CONVENTIONS.md")


def _instruction_mtimes(cwd: str) -> Tuple:
    """Cheap signature of project-instruction files for cache invalidation.

    Uses only os.path.getmtime (no subprocess), so checking the cache key is far
    cheaper than rebuilding the prompt (which runs git + reads the files).
    """
    sig = []
    for name in _INSTRUCTION_FILES:
        p = os.path.join(cwd, name)
        try:
            if os.path.isfile(p):
                sig.append((name, os.path.getmtime(p)))
        except OSError:
            pass
    return tuple(sig)


class PromptBuilder:
    """Builds composite system prompt and tool definitions accounting for MCP, Skills, and mode (Action/Explore)"""

    def __init__(self, base_system_prompt: str, base_tools: List[Dict[str, Any]], mode: str = "action", allow_task: bool = True):
        self.base_system_prompt = base_system_prompt
        self.base_tools = list(base_tools or [])
        self.mode = mode
        self.allow_task = allow_task

    def build_system_prompt(self) -> str:
        # Cache the fully-built prompt so that across the many tool-call steps of
        # a single agent turn the system prompt string is byte-identical. That
        # stability is what lets provider prompt caching (OpenAI/OpenRouter
        # automatic prefix cache, Anthropic cache_control) hit on steps 2..N and
        # avoid re-billing the ~2-4k token static overhead every step.
        cwd = os.getcwd()
        cache_key = (
            self.base_system_prompt,
            self.mode,
            self.allow_task,
            cwd,
            _instruction_mtimes(cwd),
        )
        now = time.time()
        cached = _SYSTEM_PROMPT_CACHE.get(cache_key)
        if cached is not None and now < cached[0]:
            return cached[1]
        sys_prompt = self._build_system_prompt_uncached()
        _SYSTEM_PROMPT_CACHE[cache_key] = (now + _SYSTEM_PROMPT_CACHE_TTL, sys_prompt)
        return sys_prompt

    def _build_system_prompt_uncached(self) -> str:
        cwd = os.getcwd()
        from core.mcp_manager import get_mcp_manager
        mcp_mgr = get_mcp_manager()
        mcp_snippet = mcp_mgr.get_system_prompt_snippet()
        skills_snippet = SkillManager().get_system_prompt_snippet()

        now_str = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        os_info = f"{platform.system()} {platform.release()}"
        git_info = get_git_info()

        env_lines = [
            "Environment Metadata:",
            f"- Working Directory: {cwd}",
            f"- Local Time: {now_str}",
            f"- Operating System: {os_info}"
        ]
        if git_info:
            env_lines.append(f"- Git Context: {git_info}")

        env_block = "\n".join(env_lines)

        project_snippet = get_project_instructions_snippet()
        rules_snippet = get_rules_snippet(mode=self.mode)

        # Stable prefix first (cacheable across turns); volatile env metadata
        # last so the longest possible stable prefix can be prompt-cached.
        sys_prompt = self.base_system_prompt
        if project_snippet:
            sys_prompt = f"{sys_prompt}\n\n{project_snippet}"
        if rules_snippet:
            sys_prompt = f"{sys_prompt}\n\n[USER RULES]\n{rules_snippet}"
        if skills_snippet:
            sys_prompt = f"{sys_prompt}\n\n{skills_snippet}"
        if mcp_snippet:
            sys_prompt = f"{sys_prompt}\n\n{mcp_snippet}"

        from core.mode_manager import ModeManager
        mode_def = ModeManager.get_instance().get_mode(self.mode, project_dir=cwd)
        if mode_def.prompt:
            local_plan = os.path.join(cwd, ".johnston", "plans", "plan.md")
            plan_note = f"\nRefer to plan at '{local_plan}' if present." if (mode_def.key == "action" and os.path.exists(local_plan)) else ""
            sys_prompt += f"\n\n{mode_def.prompt}{plan_note}"

        # Volatile metadata last: time/git change every turn, so keeping them at
        # the tail preserves the stable cached prefix for provider prompt caching.
        sys_prompt = f"{sys_prompt}\n\n{env_block}"

        return sys_prompt

    def build_tools(self, provider_key: str = "", model_id: str = "") -> List[Dict[str, Any]]:
        from core.mcp_manager import get_mcp_manager
        from core.mode_manager import ModeManager
        from tools.registry import ALIAS_MAP

        mcp_mgr = get_mcp_manager()
        mcp_tools = mcp_mgr.get_active_tools()
        clean_mcp_tools = [
            {"type": t["type"], "function": t["function"]} for t in mcp_tools
        ]

        all_tools = list(self.base_tools) + clean_mcp_tools

        mode_def = ModeManager.get_instance().get_mode(self.mode)
        disallowed = {t.lower() for t in (getattr(mode_def, "disallowed_tools", []) or [])}

        def _tool_allowed(tool_item: Dict[str, Any]) -> bool:
            t_name = tool_item.get("function", {}).get("name", "").strip()
            if not t_name:
                return True
            clean_name = t_name.lower()
            if clean_name.startswith("functions."):
                clean_name = clean_name.split(".", 1)[1]
            resolved = ALIAS_MAP.get(clean_name, clean_name)
            return clean_name not in disallowed and resolved not in disallowed

        filtered_tools = [t for t in all_tools if _tool_allowed(t)]

        if self.allow_task and not any(
            t.get("function", {}).get("name") in ("subagent", "Subagent") for t in filtered_tools
        ):
            filtered_tools.append(SubagentTool.schema)

        return [t for t in filtered_tools if _tool_allowed(t)]
