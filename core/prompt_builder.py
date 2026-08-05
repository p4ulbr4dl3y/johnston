import asyncio
import datetime
import os
import platform
import subprocess
import time
from typing import Any, Dict, List, Tuple

from core.skill_manager import SkillManager
from tools.invoke_subagent import InvokeSubagentTool

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
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        if _GIT_INFO_CACHE["val"]:
            return _GIT_INFO_CACHE["val"]
        # Fast path if no cache yet and loop running: run via to_thread or short return
        try:
            loop.create_task(get_git_info_async())
        except Exception:
            pass
        return _GIT_INFO_CACHE.get("val", "")

    val = _compute_git_info()
    _GIT_INFO_CACHE["ts"] = now
    _GIT_INFO_CACHE["val"] = val
    return val


async def get_git_info_async() -> str:
    now = time.time()
    if now - _GIT_INFO_CACHE["ts"] < _GIT_INFO_CACHE_TTL:
        return _GIT_INFO_CACHE["val"]
    val = await asyncio.to_thread(_compute_git_info)
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
                    if len(content) > 2500:
                        content = content[:2500] + "\n... [Project instructions truncated at 2500 chars]"
                    found_snippets.append(f"## Project Instructions ({name})\n{content}")
            except Exception:
                pass

    return "\n\n".join(found_snippets)


def get_rules_snippet(mode: str = "action") -> str:
    """Reads rules from ~/.johnston/rules and <cwd>/.johnston/rules using RulesManager."""
    from core.rules_manager import RulesManager
    return RulesManager.get_instance().get_formatted_rules(mode=mode)


DEFAULT_SYSTEM_PROMPT = """You are {model_name}, an expert AI software engineer operating inside Johnston CLI, pair programming with the user.

## Primary Goal
Assist the user with software engineering tasks through safe, high-quality, and precise code modifications and analysis.

## Core Rules
1. Research First: Inspect codebase via shell/read tools before editing. Never guess file paths or signatures.
2. Read Before Edit: Always read file contents before modifying.
3. Minimal Comments: Do not add unnecessary comments unless requested.
4. Task Planning: Use update_plan for multi-step tasks. Mark steps completed promptly.
5. Clarification: Use ask_user when intent or design requirements are ambiguous.
6. Subagents: Use subagent for background/multi-step subtasks. Use workspace='branch' for isolated git worktrees.
7. Background & Async Rule: After launching any async action (background shell, subagent, async MCP), DO NOT call any further tools. End your response immediately. System notifies you when ready.
8. Concise Communication: Be direct and clear. Summarize plan changes briefly.
9. Tool Usage: Use available function tools directly. Do not claim missing tools when listed.
10. Language Matching: Respond in the user's current message language.
11. Image Handling: If an image or file preview is missing or unreadable in your context, state this directly. Do not execute code workarounds (like OCR) without explicit user instruction."""


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

    def __init__(
        self,
        base_system_prompt: str,
        base_tools: List[Dict[str, Any]],
        mode: str = "action",
        allow_task: bool = True,
        model_name: str = "",
    ):
        self.base_system_prompt = base_system_prompt
        self.base_tools = list(base_tools or [])
        self.mode = mode
        self.allow_task = allow_task
        self.model_name = model_name

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
            self.model_name,
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
        from core.subagent_registry import SubagentRegistry
        mcp_mgr = get_mcp_manager()
        mcp_snippet = mcp_mgr.get_system_prompt_snippet()
        skills_snippet = SkillManager().get_system_prompt_snippet()
        subagents_snippet = SubagentRegistry.get_instance().get_system_prompt_snippet(project_dir=cwd)

        now_str = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
        os_info = f"{platform.system()} {platform.release()}"
        git_info = get_git_info()

        env_lines = [
            "## Environment Metadata",
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
        if "{model_name}" in sys_prompt:
            model_label = self.model_name.strip() if self.model_name and self.model_name.strip() else "an expert AI software engineer"
            sys_prompt = sys_prompt.replace("{model_name}", model_label)
        if project_snippet:
            sys_prompt = f"{sys_prompt}\n\n{project_snippet}"
        if rules_snippet:
            sys_prompt = f"{sys_prompt}\n\n## User Rules\n{rules_snippet}"
        if skills_snippet:
            sys_prompt = f"{sys_prompt}\n\n{skills_snippet}"
        if subagents_snippet:
            sys_prompt = f"{sys_prompt}\n\n{subagents_snippet}"
        if mcp_snippet:
            sys_prompt = f"{sys_prompt}\n\n{mcp_snippet}"

        from core.mode_manager import ModeManager
        mode_def = ModeManager.get_instance().get_mode(self.mode, project_dir=cwd)
        if mode_def.prompt:
            sys_prompt += f"\n\n{mode_def.prompt}"

        # Volatile metadata last: time/git change every turn, so keeping them at
        # the tail preserves the stable cached prefix for provider prompt caching.
        sys_prompt = f"{sys_prompt}\n\n{env_block}"

        return sys_prompt

    def build_tools(self, provider_key: str = "", model_id: str = "") -> List[Dict[str, Any]]:
        from core.mcp_manager import get_mcp_manager
        from core.mode_manager import ModeManager
        from tools.registry import ALIAS_MAP

        mcp_mgr = get_mcp_manager()
        mcp_tools = mcp_mgr.get_cached_tools()
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
            t.get("function", {}).get("name") in ("invoke_subagent", "subagent", "Subagent") for t in filtered_tools
        ):
            filtered_tools.append(InvokeSubagentTool.schema)

        return [t for t in filtered_tools if _tool_allowed(t)]
