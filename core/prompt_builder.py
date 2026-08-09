import asyncio
import datetime
import os
import platform
import time
from typing import Any, Dict, List, Tuple

from core.defaults.prompts import DEFAULT_SYSTEM_PROMPT, SUBAGENT_DEFAULT_SYSTEM_PROMPT
from core.git_utils import run_git
from core.skill_manager import SkillManager
from tools.invoke_subagent import InvokeSubagentTool

__all__ = ["DEFAULT_SYSTEM_PROMPT", "SUBAGENT_DEFAULT_SYSTEM_PROMPT", "PromptBuilder"]

_GIT_INFO_CACHE: Dict[str, Tuple[float, str]] = {}
_GIT_INFO_CACHE_TTL = 30.0

def get_git_info(cwd: str = None) -> str:
    """Returns current git branch for a working directory (defaults to os.getcwd()).

    Cached briefly per-directory so the multi-step agent loop does not spawn two
    git subprocesses on every tool-call step, and subagents report their own
    worktree branch instead of the parent checkout's.
    """
    key = os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())
    now = time.time()
    cached = _GIT_INFO_CACHE.get(key)
    if cached is not None and now - cached[0] < _GIT_INFO_CACHE_TTL:
        return cached[1]
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        if cached is not None:
            return cached[1]
        try:
            loop.create_task(get_git_info_async(cwd=cwd))
        except Exception:
            pass
        return cached[1] if cached else ""

    val = _compute_git_info(cwd)
    _GIT_INFO_CACHE[key] = (now, val)
    return val


async def get_git_info_async(cwd: str = None) -> str:
    key = os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())
    now = time.time()
    cached = _GIT_INFO_CACHE.get(key)
    if cached is not None and now - cached[0] < _GIT_INFO_CACHE_TTL:
        return cached[1]
    val = await asyncio.to_thread(_compute_git_info, cwd)
    _GIT_INFO_CACHE[key] = (now, val)
    return val


def _compute_git_info(cwd: str = None) -> str:
    res = run_git(["branch", "--show-current"], cwd=cwd, timeout=1)
    if res.returncode == 0 and res.stdout.strip():
        return f"branch '{res.stdout.strip()}'"

    rev_res = run_git(["rev-parse", "--short", "HEAD"], cwd=cwd, timeout=1)
    if rev_res.returncode == 0 and rev_res.stdout.strip():
        return f"detached HEAD ({rev_res.stdout.strip()})"
    return ""



def get_project_instructions_snippet(cwd: str = None) -> str:
    """Reads AGENTS.md, CLAUDE.md, .cursorrules, .windsurfrules, or CONVENTIONS.md from a working directory."""
    cwd = os.path.realpath(cwd) if cwd else os.getcwd()
    candidates = ["AGENTS.md", "CLAUDE.md", ".cursorrules", ".windsurfrules", "CONVENTIONS.md"]
    found_snippets = []

    for name in candidates:
        filepath = os.path.join(cwd, name)
        if os.path.isfile(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                if content:
                    if len(content) > 20000:
                        content = content[:20000] + "\n... [Project instructions truncated at 20000 chars]"
                    found_snippets.append(f"## Project Instructions ({name})\n{content}")
            except Exception:
                pass

    return "\n\n".join(found_snippets)


def get_rules_snippet(mode: str = "act", cwd: str = None) -> str:
    """Reads rules from ~/.johnston/rules and <cwd>/.johnston/rules using RulesManager.

    cwd selects the project rules directory so a subagent working in an isolated
    worktree sees its own `.johnston/rules` instead of the parent checkout's.
    """
    from core.rules_manager import RulesManager
    return RulesManager.get_instance().get_formatted_rules(mode=mode, project_dir=cwd)




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
        mode: str = "act",
        allow_task: bool = True,
        model_name: str = "",
        cwd: str = None,
        is_subagent: bool = False,
    ):
        self.base_system_prompt = base_system_prompt
        self.base_tools = list(base_tools or [])
        self.mode = mode
        self.allow_task = allow_task
        self.model_name = model_name
        self.cwd = os.path.realpath(cwd) if cwd else None
        self.is_subagent = is_subagent

    def build_system_prompt(self) -> str:
        # Cache the fully-built prompt so that across the many tool-call steps of
        # a single agent turn the system prompt string is byte-identical. That
        # stability is what lets provider prompt caching (OpenAI/OpenRouter
        # automatic prefix cache, Anthropic cache_control) hit on steps 2..N and
        # avoid re-billing the ~2-4k token static overhead every step.
        cwd = self.cwd or os.getcwd()
        cache_key = (
            self.base_system_prompt,
            self.mode,
            self.allow_task,
            self.model_name,
            cwd,
            self.is_subagent,
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
        cwd = self.cwd or os.getcwd()
        from core.mcp_manager import get_mcp_manager
        from core.role_registry import RoleRegistry
        mcp_mgr = get_mcp_manager()
        mcp_snippet = mcp_mgr.get_system_prompt_snippet()
        skills_snippet = SkillManager().get_system_prompt_snippet()
        subagents_snippet = (
            "" if self.is_subagent else RoleRegistry.get_instance().get_system_prompt_snippet(project_dir=cwd)
        )

        now_str = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
        os_info = f"{platform.system()} {platform.release()}"
        git_info = get_git_info(self.cwd)

        env_lines = [
            "## Environment Metadata",
            f"- Working Directory: {cwd}",
            f"- Current Date: {now_str}",
            f"- Operating System: {os_info}"
        ]
        if git_info:
            env_lines.append(f"- Git Context: {git_info}")

        env_block = "\n".join(env_lines)

        project_snippet = get_project_instructions_snippet(self.cwd)
        rules_snippet = get_rules_snippet(mode=self.mode, cwd=self.cwd)

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

        if not self.is_subagent:
            from core.role_registry import RoleRegistry
            mode_def = RoleRegistry.get_instance().get_role(self.mode, project_dir=cwd)
            if mode_def.prompt:
                sys_prompt += f"\n\n{mode_def.prompt}"

        # Volatile metadata last: time/git change every turn, so keeping them at
        # the tail preserves the stable cached prefix for provider prompt caching.
        sys_prompt = f"{sys_prompt}\n\n{env_block}"

        return sys_prompt

    def build_tools(self, provider_key: str = "", model_id: str = "") -> List[Dict[str, Any]]:
        from core.mcp_manager import get_mcp_manager
        from core.role_registry import RoleRegistry
        from tools.registry import normalize_tool_name

        mcp_mgr = get_mcp_manager()
        mcp_tools = mcp_mgr.get_cached_tools()
        clean_mcp_tools = [
            {"type": t["type"], "function": t["function"]} for t in mcp_tools
        ]

        all_tools = list(self.base_tools) + clean_mcp_tools

        mode_def = RoleRegistry.get_instance().get_role(self.mode)
        disallowed = {t.lower() for t in (getattr(mode_def, "disallowed_tools", []) or [])}

        def _tool_allowed(tool_item: Dict[str, Any]) -> bool:
            t_name = tool_item.get("function", {}).get("name", "").strip()
            if not t_name:
                return True
            clean_name = t_name.lower()
            resolved = normalize_tool_name(clean_name)
            if self.is_subagent:
                subagent_forbidden = {
                    "invoke_subagent", "subagent", "manage_subagent",
                    "manage_shell", "manage_subagent", "ask_user"
                }
                if clean_name in subagent_forbidden or resolved in subagent_forbidden:
                    return False

            return clean_name not in disallowed and resolved not in disallowed

        filtered_tools = [t for t in all_tools if _tool_allowed(t)]

        if not self.is_subagent and self.allow_task and not any(
            t.get("function", {}).get("name") in ("invoke_subagent", "subagent", "Subagent") for t in filtered_tools
        ):
            filtered_tools.append(InvokeSubagentTool.schema)

        allowed_tools = [t for t in filtered_tools if _tool_allowed(t)]

        def _sort_tool_schema(tool_dict: Dict[str, Any]) -> Dict[str, Any]:
            import copy
            t = copy.deepcopy(tool_dict)
            fn = t.get("function", {})
            params = fn.get("parameters", {})
            if isinstance(params, dict):
                props = params.get("properties")
                if isinstance(props, dict):
                    params["properties"] = dict(sorted(props.items()))
                req = params.get("required")
                if isinstance(req, list):
                    params["required"] = sorted(req)
            return t

        sorted_tools = [_sort_tool_schema(t) for t in allowed_tools]
        sorted_tools.sort(key=lambda t: (t.get("function", {}) or {}).get("name", ""))
        return sorted_tools
