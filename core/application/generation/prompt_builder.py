import asyncio
import datetime
import os
import platform
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from core.application.skills.manager import SkillManager
from core.domain.defaults.prompts import DEFAULT_SYSTEM_PROMPT, SUBAGENT_DEFAULT_SYSTEM_PROMPT

INSTRUCTION_FILES = ["AGENTS.md", "CLAUDE.md", ".cursorrules", ".windsurfrules", "CONVENTIONS.md"]

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "SUBAGENT_DEFAULT_SYSTEM_PROMPT",
    "PromptBuilder",
    "INSTRUCTION_FILES",
]

_GIT_INFO_CACHE: Dict[str, Tuple[float, str]] = {}
_GIT_INFO_CACHE_TTL = 30.0

_PROJECT_INSTR_CACHE_MAX = 64
_STABLE_CORE_CACHE_MAX = 256
_TOOLS_CACHE_MAX = 32

# (realpath cwd) -> (mtime/size signature, snippet). Invalidates when any
# instruction file appears/disappears or its mtime changes.
_PROJECT_INSTRUCTION_CACHE: Dict[str, Tuple[tuple, str]] = {}

# Semantic cache for the stable (non-volatile) prefix of the system prompt.
# Keyed by the assembled stable parts so it only rebuilds when roles / rules /
# skills / instructions / mcp tool map actually change.
_STABLE_CORE_CACHE: "OrderedDict[tuple, str]" = OrderedDict()

# Reused SkillManager instances keyed by project dir, so the agent loop does not
# re-provision/re-scan skills on every turn.
_SKILL_MANAGERS: Dict[str, SkillManager] = {}

# Pre-sorted tool schema cache keyed by a content identity (tool object ids +
# role flags). build_tools deepcopy+sorts only on cache miss.
_TOOLS_CACHE: "OrderedDict[tuple, List[Dict[str, Any]]]" = OrderedDict()


def _cache_set(cache, key, value, max_size: int) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > max_size:
        cache.popitem(last=False)


def _get_skill_manager(cwd: Optional[str]) -> SkillManager:
    key = os.path.realpath(cwd) if cwd else os.getcwd()
    mgr = _SKILL_MANAGERS.get(key)
    if mgr is None:
        mgr = SkillManager(project_dir=key)
        _SKILL_MANAGERS[key] = mgr
    return mgr



def _cached_git_info(cwd: Optional[str] = None) -> Optional[str]:
    """Return the cached git-info string for a directory, or None when stale/absent."""
    key = os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())
    cached = _GIT_INFO_CACHE.get(key)
    if cached is not None and time.time() - cached[0] < _GIT_INFO_CACHE_TTL:
        return cached[1]
    return None


def _cache_git_info(cwd: Optional[str] = None, value: str = "") -> str:
    _GIT_INFO_CACHE[os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())] = (time.time(), value)
    return value


def get_git_info(cwd: str = None) -> str:
    """Returns current git branch for a working directory (defaults to os.getcwd()).

    Cached briefly per-directory so the multi-step agent loop does not spawn two
    git subprocesses on every tool-call step, and subagents report their own
    worktree branch instead of the parent checkout's.
    """
    key = os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())
    cached = _cached_git_info(key)
    if cached is not None:
        return cached

    last_known = _GIT_INFO_CACHE.get(key, (0, ""))[1]

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        try:
            loop.create_task(get_git_info_async(cwd=cwd))
        except Exception:
            pass
        return last_known
    return _cache_git_info(key, _compute_git_info(cwd))


async def get_git_info_async(cwd: str = None) -> str:
    key = os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())
    cached = _cached_git_info(key)
    if cached is not None:
        return cached
    return _cache_git_info(key, await asyncio.to_thread(_compute_git_info, cwd))


def _compute_git_info(cwd: str = None) -> str:
    from core.infrastructure.runtime.git_utils import format_git_branch_info

    return format_git_branch_info(cwd=cwd)


def _project_instr_signature(cwd: str) -> tuple:
    """Cheap (name, mtime_ns, size) signature for every instruction file present.

    Detects additions, removals and edits without re-reading file contents.
    """
    entries = []
    for name in INSTRUCTION_FILES:
        fpath = os.path.join(cwd, name)
        try:
            st = os.stat(fpath)
            entries.append((name, st.st_mtime_ns, st.st_size))
        except OSError:
            positions = {e[0] for e in entries}
            if name not in positions:
                entries.append((name, 0, 0))
    return tuple(entries)


def get_project_instructions_snippet(cwd: str = None) -> str:
    """Reads INSTRUCTION_FILES from a working directory.

    Cached per-directory by an mtime/size signature; files are only re-read
    when they change, so the agent loop does not re-open disk files every turn.
    """
    cwd = os.path.realpath(cwd) if cwd else os.getcwd()
    sig = _project_instr_signature(cwd)
    cached = _PROJECT_INSTRUCTION_CACHE.get(cwd)
    if cached is not None and cached[0] == sig:
        return cached[1]

    found_snippets = []
    for name in INSTRUCTION_FILES:
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

    result = "\n\n".join(found_snippets)
    if len(_PROJECT_INSTRUCTION_CACHE) >= _PROJECT_INSTR_CACHE_MAX:
        dict.popitem(_PROJECT_INSTRUCTION_CACHE, last=False)
    _PROJECT_INSTRUCTION_CACHE[cwd] = (sig, result)
    return result


async def get_project_instructions_snippet_async(cwd: str = None) -> str:
    """Async variant: reads AGENTS.md/CLAUDE.md on a thread on cache miss.

    Cache-hit calls return immediately without touching the thread pool.
    """
    cwd = os.path.realpath(cwd) if cwd else os.getcwd()
    sig = _project_instr_signature(cwd)
    cached = _PROJECT_INSTRUCTION_CACHE.get(cwd)
    if cached is not None and cached[0] == sig:
        return cached[1]
    return await asyncio.to_thread(get_project_instructions_snippet, cwd)


def get_rules_snippet(role: str = "worker", cwd: str = None) -> str:
    """Reads rules from ~/.johnston/rules and <cwd>/.johnston/rules using RulesManager.

    cwd selects the project rules directory so a subagent working in an isolated
    worktree sees its own `.johnston/rules` instead of the parent checkout's.
    """
    from core.application.rules.rules import RulesManager

    rules = RulesManager.get_instance().get_active_rules(role=role, project_dir=cwd)
    from core.infrastructure.runtime.prompt_markdown import format_rules_markdown

    return format_rules_markdown(rules)


async def get_rules_snippet_async(role: str = "worker", cwd: str = None) -> str:
    """Async variant of ``get_rules_snippet``: reads rules on a thread."""
    return await asyncio.to_thread(get_rules_snippet, role, cwd)


class PromptBuilder:
    """Builds composite system prompt and tool definitions accounting for MCP, Skills, and agent role (worker/explorer/orchestrator)"""

    def __init__(
        self,
        base_system_prompt: str,
        base_tools: List[Dict[str, Any]],
        role: str = "worker",
        allow_task: bool = True,
        model_name: str = "",
        cwd: str = None,
        is_subagent: bool = False,
        subagent_schema: Optional[Dict] = None,
    ):
        self.base_system_prompt = base_system_prompt
        self.base_tools = list(base_tools or [])
        self.role = role
        self.allow_task = allow_task
        self.model_name = model_name
        self.cwd = os.path.realpath(cwd) if cwd else None
        self.is_subagent = is_subagent
        self.subagent_schema = subagent_schema

    def build_system_prompt(self) -> str:
        cwd = self.cwd or os.getcwd()
        from core.infrastructure.mcp import get_mcp_manager
        from core.role_registry import RoleRegistry

        mcp_mgr = get_mcp_manager()
        mcp_snippet = mcp_mgr.get_system_prompt_snippet()
        from core.infrastructure.runtime.prompt_markdown import format_skills_markdown

        skills_snippet = format_skills_markdown(_get_skill_manager(self.cwd).get_system_prompt_skills())
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
            f"- Operating System: {os_info}",
        ]
        if git_info:
            env_lines.append(f"- Git Context: {git_info}")

        env_block = "\n".join(env_lines)

        stable_core = self._build_stable_core(mcp_snippet, skills_snippet, subagents_snippet)

        # Stable prefix first (cacheable across turns); volatile env metadata
        # last so the longest possible stable prefix can be prompt-cached.
        sys_prompt = stable_core

        # Volatile metadata last: time/git change every turn, so keeping them at
        # the tail preserves the stable cached prefix for provider prompt caching.
        sys_prompt = f"{sys_prompt}\n\n{env_block}"

        return sys_prompt

    async def build_system_prompt_async(self) -> str:
        """Async variant of ``build_system_prompt`` for the async agent loop.

        On cache miss, file/system-prompt-part reads (project instructions, rules,
        skills tree scan) run on a worker thread instead of blocking the event loop.
        """
        cwd = self.cwd or os.getcwd()
        from core.infrastructure.mcp import get_mcp_manager
        from core.role_registry import RoleRegistry

        mcp_mgr = get_mcp_manager()
        mcp_snippet = mcp_mgr.get_system_prompt_snippet()
        from core.infrastructure.runtime.prompt_markdown import format_skills_markdown

        skills_snippet = format_skills_markdown(
            await asyncio.to_thread(_get_skill_manager(self.cwd).get_system_prompt_skills)
        )
        subagents_snippet = (
            "" if self.is_subagent else RoleRegistry.get_instance().get_system_prompt_snippet(project_dir=cwd)
        )

        now_str = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
        os_info = f"{platform.system()} {platform.release()}"
        git_info = await get_git_info_async(self.cwd)

        env_lines = [
            "## Environment Metadata",
            f"- Working Directory: {cwd}",
            f"- Current Date: {now_str}",
            f"- Operating System: {os_info}",
        ]
        if git_info:
            env_lines.append(f"- Git Context: {git_info}")

        env_block = "\n".join(env_lines)

        stable_core = await self._build_stable_core_async(mcp_snippet, skills_snippet, subagents_snippet)

        # Stable prefix first (cacheable across turns); volatile env metadata
        # last so the longest possible stable prefix can be prompt-cached.
        sys_prompt = stable_core

        # Volatile metadata last: time/git change every turn, so keeping them at
        # the tail preserves the stable cached prefix for provider prompt caching.
        sys_prompt = f"{sys_prompt}\n\n{env_block}"

        return sys_prompt

    def _build_stable_core(self, mcp_snippet, skills_snippet, subagents_snippet) -> str:
        """Assemble + cache the stable (non-volatile) system-prompt prefix.

        Only rebuilds when the parts it depends on change: base prompt, role
        definition, project instructions, rules, skills, subagents or the MCP
        snippet. Volatile environment metadata (date/git) stays out of this
        build so it stays cacheable across turns.
        """
        from core.role_registry import RoleRegistry

        sys_prompt = self.base_system_prompt if self.base_system_prompt else ""
        if "{model_name}" in sys_prompt:
            model_label = (
                self.model_name.strip()
                if self.model_name and self.model_name.strip()
                else "an expert AI software engineer"
            )
            sys_prompt = sys_prompt.replace("{model_name}", model_label)

        project_snippet = get_project_instructions_snippet(self.cwd)
        rules_snippet = get_rules_snippet(role=self.role, cwd=self.cwd)

        role_def = None
        if not self.is_subagent:
            role_def = RoleRegistry.get_instance().get_role(self.role, project_dir=self.cwd or os.getcwd())
            if getattr(role_def, "prompt", None):
                sys_prompt += f"\n\n{role_def.prompt}"

        # Cache key from the stable components. role_def is represented by its
        # content so the cache invalidates when the role definition changes even
        # if registry internals were refreshed in place.
        def _ident(obj):
            if obj is None:
                return None
            return (id(obj), getattr(obj, "key", None), getattr(obj, "prompt", None))

        key = (
            sys_prompt,
            project_snippet,
            rules_snippet,
            skills_snippet,
            subagents_snippet,
            mcp_snippet,
            self.role,
            _ident(role_def),
        )

        cached = _STABLE_CORE_CACHE.get(key)
        if cached is not None:
            return cached

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

        _cache_set(_STABLE_CORE_CACHE, key, sys_prompt, _STABLE_CORE_CACHE_MAX)
        return sys_prompt

    async def _build_stable_core_async(self, mcp_snippet, skills_snippet, subagents_snippet) -> str:
        """Async variant: same stable-prefix assembly, but file reads (project
        instructions, rules) happen on a worker thread on cache miss."""
        from core.role_registry import RoleRegistry

        sys_prompt = self.base_system_prompt if self.base_system_prompt else ""
        if "{model_name}" in sys_prompt:
            model_label = (
                self.model_name.strip()
                if self.model_name and self.model_name.strip()
                else "an expert AI software engineer"
            )
            sys_prompt = sys_prompt.replace("{model_name}", model_label)

        project_snippet = await get_project_instructions_snippet_async(self.cwd)
        rules_snippet = await get_rules_snippet_async(role=self.role, cwd=self.cwd)

        role_def = None
        if not self.is_subagent:
            role_def = RoleRegistry.get_instance().get_role(self.role, project_dir=self.cwd or os.getcwd())
            if getattr(role_def, "prompt", None):
                sys_prompt += f"\n\n{role_def.prompt}"

        # Cache key from the stable components. role_def is represented by its
        # content so the cache invalidates when the role definition changes even
        # if registry internals were refreshed in place.
        def _ident(obj):
            if obj is None:
                return None
            return (id(obj), getattr(obj, "key", None), getattr(obj, "prompt", None))

        key = (
            sys_prompt,
            project_snippet,
            rules_snippet,
            skills_snippet,
            subagents_snippet,
            mcp_snippet,
            self.role,
            _ident(role_def),
        )

        cached = _STABLE_CORE_CACHE.get(key)
        if cached is not None:
            return cached

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

        _cache_set(_STABLE_CORE_CACHE, key, sys_prompt, _STABLE_CORE_CACHE_MAX)
        return sys_prompt

    def build_tools(self, provider_key: str = "") -> List[Dict[str, Any]]:
        from core.domain.policies.role_policy import role_tool_error
        from core.infrastructure.mcp import get_mcp_manager
        from core.role_registry import RoleRegistry

        mcp_mgr = get_mcp_manager()
        mcp_tools = mcp_mgr.get_cached_tools()
        clean_mcp_tools = [{"type": t["type"], "function": t["function"]} for t in mcp_tools]

        all_tools = list(self.base_tools) + clean_mcp_tools

        role_def = RoleRegistry.get_instance().get_role(self.role, project_dir=self.cwd or os.getcwd())

        # Single role-tool policy (shared with roles/tools and role_registry).
        # is_subagent passes the subagent-excluded-tool check into the core policy.
        filtered_tools = [
            t
            for t in all_tools
            if role_tool_error(role_def, t.get("function", {}).get("name", ""), is_subagent=self.is_subagent) is None
        ]

        if (
            not self.is_subagent
            and self.allow_task
            and self.subagent_schema
            and not any(
                t.get("function", {}).get("name", "").lower() in ("invoke_subagent", "subagent")
                for t in filtered_tools
            )
        ):
            filtered_tools.append(self.subagent_schema)

        if self.is_subagent:
            from core.roles.tools import _rebuild_tool

            filtered_tools = [_rebuild_tool(t) for t in filtered_tools]

        allowed_tools = filtered_tools

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
                    try:
                        params["required"] = sorted(req)
                    except TypeError:
                        params["required"] = req
            return t

        # Identity key lets us reuse the last pre-sorted build when the tool
        # objects (and role flags) are unchanged this turn, skipping the
        # per-schema deepcopy + re-sort. A fresh build always happens after any
        # tool swap because old object ids drop out of the key.
        key = (tuple(id(t) for t in allowed_tools), self.is_subagent, self.allow_task)
        cached = _TOOLS_CACHE.get(key)
        if cached is not None:
            return list(cached)

        sorted_tools = [_sort_tool_schema(t) for t in allowed_tools]
        sorted_tools.sort(key=lambda t: (t.get("function", {}) or {}).get("name", ""))
        _cache_set(_TOOLS_CACHE, key, sorted_tools, _TOOLS_CACHE_MAX)
        return list(sorted_tools)
