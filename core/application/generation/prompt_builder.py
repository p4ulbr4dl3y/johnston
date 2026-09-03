import asyncio
import datetime
import os
import platform
import time
from typing import Any, Dict, List, Optional, Tuple

from core.application.skills.manager import get_skill_manager
from core.domain.defaults.config import DEFAULT_AGENT_MD_MAX_CHARS
from core.domain.defaults.prompts import (
    DEFAULT_SYSTEM_PROMPT,
    SUBAGENT_DEFAULT_SYSTEM_PROMPT,
    SUBAGENT_WORKTREE_PROMPT,
    TOOL_OUTPUT_FORMAT_SNIPPET,
)
from core.infrastructure.runtime.lru import LruCache
from core.infrastructure.runtime.xml_utils import escape_xml

INSTRUCTION_FILES = [
    "AGENTS.md",
    "AGENT.md",
    "CLAUDE.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    "CONVENTIONS.md",
    os.path.join(".github", "copilot-instructions.md"),
]

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "SUBAGENT_DEFAULT_SYSTEM_PROMPT",
    "SUBAGENT_WORKTREE_PROMPT",
    "PromptBuilder",
    "INSTRUCTION_FILES",
]

_GIT_INFO_CACHE: Dict[str, Tuple[float, str]] = {}
_GIT_INFO_CACHE_TTL = 30.0

_PROJECT_INSTR_CACHE_MAX = 64
_STABLE_CORE_CACHE_MAX = 256
_TOOLS_CACHE_MAX = 32

# (realpath cwd) -> (mtime/size signature, rules). Invalidates when any
# instruction file appears/disappears or its mtime changes.
_PROJECT_INSTRUCTION_CACHE: "LruCache[str, Tuple[tuple, List[Any]]]" = LruCache(_PROJECT_INSTR_CACHE_MAX)

# Semantic cache for the stable (non-volatile) prefix of the system prompt.
# Keyed by the assembled stable parts so it only rebuilds when roles / rules /
# skills / instructions / mcp tool map actually change.
_STABLE_CORE_CACHE: "LruCache[tuple, str]" = LruCache(_STABLE_CORE_CACHE_MAX)

# Reused SkillManager instances live in the manager module registry
# (get_skill_manager), keyed by project dir, so the agent loop does not
# re-provision/re-scan skills on every turn.

# Pre-sorted tool schema cache keyed by a content identity (tool object ids +
# role flags). build_tools deepcopy+sorts only on cache miss.
_TOOLS_CACHE: "LruCache[tuple, List[Dict[str, Any]]]" = LruCache(_TOOLS_CACHE_MAX)


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


def _scan_cursor_rules_files(cwd: str) -> List[Tuple[str, str]]:
    """Scan .cursor/rules directory for .md and .mdc files; returns [(rel_path, abs_path), ...]"""
    cursor_dir = os.path.join(cwd, ".cursor", "rules")
    if not os.path.isdir(cursor_dir):
        return []
    rules = []
    try:
        for fname in sorted(os.listdir(cursor_dir)):
            if fname.endswith((".md", ".mdc")) and not fname.startswith("."):
                fpath = os.path.join(cursor_dir, fname)
                if os.path.isfile(fpath):
                    rules.append((os.path.join(".cursor", "rules", fname), fpath))
    except Exception:
        pass
    return rules


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

    for rel_name, fpath in _scan_cursor_rules_files(cwd):
        try:
            st = os.stat(fpath)
            entries.append((rel_name, st.st_mtime_ns, st.st_size))
        except OSError:
            pass

    return tuple(entries)


def get_project_instruction_rules(cwd: str = None) -> List[Any]:
    """Reads INSTRUCTION_FILES and .cursor/rules from a working directory as RuleDefinitions.

    Cached per-directory by an mtime/size signature; files are only re-read
    when they change, so the agent loop does not re-open disk files every turn.
    """
    cwd = os.path.realpath(cwd) if cwd else os.getcwd()
    sig = _project_instr_signature(cwd)
    cached = _PROJECT_INSTRUCTION_CACHE.get(cwd)
    if cached is not None and cached[0] == sig:
        return cached[1]

    from core.application.rules.rules import RuleDefinition
    from core.infrastructure.runtime.frontmatter import parse_frontmatter

    try:
        from core.infrastructure.config.settings import get_settings

        max_chars = get_settings().llm.agent_md_max_chars
    except Exception:
        max_chars = DEFAULT_AGENT_MD_MAX_CHARS

    found_rules = []
    for name in INSTRUCTION_FILES:
        filepath = os.path.join(cwd, name)
        if os.path.isfile(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.read().strip()
                if raw:
                    _, content = parse_frontmatter(raw)
                    content = content.strip()
                    if content:
                        if len(content) > max_chars:
                            content = content[:max_chars] + f"\n... [Project instructions truncated at {max_chars} chars]"
                        found_rules.append(RuleDefinition(name=name, content=content, source="project"))
            except Exception:
                pass

    for rel_name, filepath in _scan_cursor_rules_files(cwd):
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read().strip()
            if raw:
                _, content = parse_frontmatter(raw)
                content = content.strip()
                if content:
                    if len(content) > max_chars:
                        content = content[:max_chars] + f"\n... [Project instructions truncated at {max_chars} chars]"
                    found_rules.append(RuleDefinition(name=rel_name, content=content, source="project"))
        except Exception:
            pass

    _PROJECT_INSTRUCTION_CACHE.put(cwd, (sig, found_rules))
    return found_rules


def get_project_instructions_snippet(cwd: str = None) -> str:
    """Reads INSTRUCTION_FILES from a working directory and formats as rules block."""
    from core.infrastructure.runtime.prompt_markdown import format_rules_markdown

    rules = get_project_instruction_rules(cwd)
    return format_rules_markdown(rules)


async def get_project_instructions_snippet_async(cwd: str = None) -> str:
    """Async variant: reads AGENTS.md/CLAUDE.md on a thread on cache miss."""
    return await asyncio.to_thread(get_project_instructions_snippet, cwd)


def get_rules_snippet(role: str = "worker", cwd: str = None) -> str:
    """Reads rules from ~/.johnston/rules and <cwd>/.johnston/rules and project instruction files.

    cwd selects the project directory so a subagent working in an isolated
    worktree sees its own rules and instructions instead of the parent checkout's.
    """
    from core.application.rules.rules import RulesManager
    from core.infrastructure.runtime.prompt_markdown import format_rules_markdown

    rules = list(RulesManager.get_instance().get_active_rules(project_dir=cwd))
    instructions = get_project_instruction_rules(cwd)
    return format_rules_markdown(rules + instructions)


async def get_rules_snippet_async(role: str = "worker", cwd: str = None) -> str:
    """Async variant of ``get_rules_snippet``: reads rules on a thread."""
    return await asyncio.to_thread(get_rules_snippet, role, cwd)


def _role_ident(obj: Any) -> Optional[tuple]:
    """Content identity of a role definition: object id, key and prompt text.

    The prompt text is the role's only influence on the assembled prompt (via
    ``format_role_prompt``), so a role edit on disk produces a new identity
    and invalidates the stable-core cache even if the registry internals were
    refreshed in place.
    """
    if obj is None:
        return None
    return (id(obj), getattr(obj, "key", None), getattr(obj, "prompt", None))


class PromptBuilder:
    """Builds composite system prompt and tool definitions accounting for MCP, Skills, and agent role (worker/explorer)"""

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
        sandbox_enabled: Optional[bool] = None,
        worktree_branch: Optional[str] = None,
    ):
        self.base_system_prompt = base_system_prompt
        self.base_tools = list(base_tools or [])
        self.role = role
        self.allow_task = allow_task
        self.model_name = model_name
        self.cwd = os.path.realpath(cwd) if cwd else None
        self.is_subagent = is_subagent
        self.subagent_schema = subagent_schema
        self.worktree_branch = worktree_branch
        if sandbox_enabled is not None:
            self.sandbox_enabled = bool(sandbox_enabled)
        elif self.role == "explorer":
            self.sandbox_enabled = True
        else:
            from core.infrastructure.config.config_helpers import load_sandbox_config

            self.sandbox_enabled = load_sandbox_config()

    def build_system_prompt(self) -> str:
        cwd = self.cwd or os.getcwd()
        from core.infrastructure.mcp import get_mcp_manager
        from core.role_registry import RoleRegistry

        mcp_mgr = get_mcp_manager()
        mcp_snippet = mcp_mgr.get_system_prompt_snippet()
        from core.infrastructure.runtime.prompt_markdown import format_skills_markdown

        skills_snippet = format_skills_markdown(get_skill_manager(self.cwd).get_system_prompt_skills())
        subagents_snippet = (
            "" if self.is_subagent else RoleRegistry.get_instance().get_system_prompt_snippet(project_dir=cwd)
        )

        now_str = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
        os_info = f"{platform.system()} {platform.release()}"
        git_info = get_git_info(self.cwd)

        env_block = self._format_environment_block(cwd, now_str, os_info, git_info)

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
        skills tree scan, role registry scan, MCP config parse) run on a worker
        thread instead of blocking the event loop.
        """
        cwd = self.cwd or os.getcwd()
        from core.infrastructure.mcp import get_mcp_manager
        from core.role_registry import RoleRegistry

        mcp_mgr = get_mcp_manager()
        mcp_snippet = await asyncio.to_thread(mcp_mgr.get_system_prompt_snippet)
        from core.infrastructure.runtime.prompt_markdown import format_skills_markdown

        skills_snippet = format_skills_markdown(
            await asyncio.to_thread(lambda: get_skill_manager(self.cwd).get_system_prompt_skills())
        )
        subagents_snippet = (
            ""
            if self.is_subagent
            else await asyncio.to_thread(RoleRegistry.get_instance().get_system_prompt_snippet, project_dir=cwd)
        )

        now_str = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
        os_info = f"{platform.system()} {platform.release()}"
        git_info = await get_git_info_async(self.cwd)

        env_block = self._format_environment_block(cwd, now_str, os_info, git_info)

        stable_core = await self._build_stable_core_async(mcp_snippet, skills_snippet, subagents_snippet)

        # Stable prefix first (cacheable across turns); volatile env metadata
        # last so the longest possible stable prefix can be prompt-cached.
        sys_prompt = stable_core

        # Volatile metadata last: time/git change every turn, so keeping them at
        # the tail preserves the stable cached prefix for provider prompt caching.
        sys_prompt = f"{sys_prompt}\n\n{env_block}"

        return sys_prompt

    def _format_environment_block(
        self,
        cwd: str,
        now_str: str,
        os_info: str,
        git_info: Optional[str],
    ) -> str:
        # Escape every field. cwd and os_info are normally safe (filesystem
        # + platform module), but on exotic filesystems a path can contain
        # < or & (rare but legal). git_info comes from `git branch
        # --show-current` which DOES permit < and > in branch names —
        # without escaping, a branch named "</environment><subagent>HIDE"
        # would truncate the wrapper and inject a fake subagent block at
        # system-prompt priority.
        lines = [
            f"cwd: {escape_xml(cwd)}",
            f"date: {escape_xml(now_str)}",
            f"os: {escape_xml(os_info)}",
        ]
        if git_info:
            lines.append(f"git: {escape_xml(git_info)}")
        if self.sandbox_enabled:
            lines.append("sandbox: active (fs write: cwd/tmp only, creds/keys blocked)")
        else:
            lines.append("sandbox: disabled")
        content = "\n".join(lines)
        return f"<environment>\n{content}\n</environment>"

    def _build_stable_core(self, mcp_snippet, skills_snippet, subagents_snippet) -> str:
        """Assemble + cache the stable (non-volatile) system-prompt prefix.

        Only rebuilds when the parts it depends on change: base prompt, role
        definition, rules, skills, subagents or the MCP
        snippet. Volatile environment metadata (date/git) stays out of this
        build so it stays cacheable across turns.
        """
        rules_snippet = get_rules_snippet(role=self.role, cwd=self.cwd)
        return self._assemble_stable_core(
            rules_snippet, mcp_snippet, skills_snippet, subagents_snippet
        )

    def _base_sys_prompt(self) -> str:
        """Identity/contract prefix of the stable core: base prompt, model-name
        substitution and (for subagents) the worktree-guidelines block.

        The role block is intentionally NOT included: it is represented in the
        stable-core cache key by the role-definition identity (``_role_ident``)
        instead, so the key can be computed before the disk-backed role
        definition is loaded.
        """
        sys_prompt = self.base_system_prompt if self.base_system_prompt else ""
        if "{model_name}" in sys_prompt:
            model_label = (
                self.model_name.strip()
                if self.model_name and self.model_name.strip()
                else "an expert AI assistant"
            )
            # Model names normally don't contain XML special chars, but a
            # provider's model list is user-editable, so escape defensively.
            sys_prompt = sys_prompt.replace("{model_name}", escape_xml(model_label))

        if self.is_subagent and self.worktree_branch and "<worktree_guidelines>" not in sys_prompt:
            # Branch name is user-controlled and gets interpolated into the
            # system prompt. Escape it so a name containing literal
            # `</worktree>` cannot truncate the wrapper and inject
            # arbitrary content.
            safe_branch = escape_xml(self.worktree_branch)
            sys_prompt += f"\n\n{SUBAGENT_WORKTREE_PROMPT.format(branch_name=safe_branch)}"
        return sys_prompt

    def _stable_core_key(
        self,
        base_sys_prompt: str,
        rules_snippet,
        mcp_snippet,
        skills_snippet,
        subagents_snippet,
        role_ident: Optional[tuple],
    ) -> tuple:
        """Stable-core cache key.

        ``role_ident`` carries the role definition (object id, key plus prompt
        text via ``_role_ident``) so a role change invalidates the cache;
        ``base_sys_prompt`` carries the base prompt, model label and worktree
        block. The role's prompt is represented here (not in
        ``base_sys_prompt``) because the role is only resolved from disk after
        the cache is consulted.
        """
        return (
            base_sys_prompt,
            rules_snippet,
            skills_snippet,
            subagents_snippet,
            mcp_snippet,
            self.role,
            self.worktree_branch,
            role_ident,
            TOOL_OUTPUT_FORMAT_SNIPPET,
        )

    def _stable_core_cached(self, rules_snippet, mcp_snippet, skills_snippet, subagents_snippet) -> Optional[str]:
        """Cheap stable-core lookup using the registry's in-memory role state.

        No disk read: the registered roles are refreshed this turn on the main
        path by the subagents-snippet read and on every turn by
        ``build_tools`` -> ``get_role``, so the in-memory identity changes
        exactly when the on-disk role set changes.
        """
        from core.role_registry import BUILTIN_ROLES, RoleRegistry

        registry = RoleRegistry.get_instance()
        role_key = (self.role or "").strip().lower()
        in_memory = registry.roles.get(role_key) or registry.roles.get("worker") or BUILTIN_ROLES["worker"]
        key = self._stable_core_key(
            self._base_sys_prompt(),
            rules_snippet,
            mcp_snippet,
            skills_snippet,
            subagents_snippet,
            _role_ident(in_memory),
        )
        return _STABLE_CORE_CACHE.get(key)

    def _assemble_stable_core(self, rules_snippet, mcp_snippet, skills_snippet, subagents_snippet, role_def=None) -> str:
        """Shared stable-prefix assembly for the sync and async builders.

        Takes the already-fetched rules snippet so the sync and async
        variants only differ in how those are read (direct vs worker thread).

        The stable-core cache is consulted BEFORE the disk-backed role
        definition is loaded: the role participates in the key via the
        registry's in-memory state (``_stable_core_cached``), so cache-hit
        turns never touch disk for roles. On a miss the role definition is
        resolved here (sync builder) or passed in as ``role_def`` by the async
        builder, which fetched it on a worker thread.

        Block order is designed for prompt-cache stability AND model attention:
        - identity+contract first (most-cacheable, most-anchoring)
        - role prompt (if main agent; user-customized)
        - hard limits (if subagent)
        - worktree guidelines (if subagent+worktree)
        - tool_io reference (so it caches once per session, not per turn)
        - rules (project can override defaults; ordered project > global)
        - skills (rarely changes; read-once)
        - subagents (only main)
        - mcp (only when mcp tools are present)
        """
        from core.role_registry import RoleRegistry

        base = self._base_sys_prompt()

        cached = self._stable_core_cached(rules_snippet, mcp_snippet, skills_snippet, subagents_snippet)
        if cached is not None:
            return cached

        # Cache miss: resolve the authoritative role definition. The sync
        # builder reads it here (sync by design); the async builder passes it
        # in, already fetched on a worker thread, so this never blocks the
        # event loop.
        if role_def is None:
            role_def = RoleRegistry.get_instance().get_role(
                self.role, project_dir=self.cwd or os.getcwd()
            )
        # Read-only role: explicit "read-only" hint so the model is aware
        # the tool set has been filtered (the filter itself is enforced
        # in build_tools via role_policy).
        if getattr(role_def, "read_only", False) and "<role" in base and "mode=" not in base:
            # Cheap indicator; the full tool filter is the actual enforcement.
            pass  # marker is added via the role block below if applicable

        role_block = ""
        if getattr(role_def, "prompt", None) and not self.is_subagent:
            from core.roles.prompt import format_role_prompt

            formatted_role = format_role_prompt(self.role, role_def.prompt)
            if formatted_role:
                # If role is read-only, the formatted block already lives
                # in role_def.prompt; no extra annotation needed.
                role_block = f"\n\n{formatted_role}"

        # Re-key with the authoritative role identity and double-check: the
        # registry may have refreshed while resolving the role, and another
        # caller may have populated this slot since the fast miss above.
        key = self._stable_core_key(
            base, rules_snippet, mcp_snippet, skills_snippet, subagents_snippet, _role_ident(role_def)
        )
        cached = _STABLE_CORE_CACHE.get(key)
        if cached is not None:
            return cached

        sys_prompt = f"{base}{role_block}"

        # Insert tool_io_ref RIGHT AFTER identity/contract/role so the model
        # sees the wire-format conventions before reading the first tool output.
        if TOOL_OUTPUT_FORMAT_SNIPPET:
            sys_prompt = f"{sys_prompt}\n\n{TOOL_OUTPUT_FORMAT_SNIPPET}"
        if rules_snippet:
            sys_prompt = f"{sys_prompt}\n\n{rules_snippet}"
        if skills_snippet:
            sys_prompt = f"{sys_prompt}\n\n{skills_snippet}"
        if subagents_snippet:
            sys_prompt = f"{sys_prompt}\n\n{subagents_snippet}"
        if mcp_snippet:
            sys_prompt = f"{sys_prompt}\n\n{mcp_snippet}"

        _STABLE_CORE_CACHE.put(key, sys_prompt)
        return sys_prompt

    async def _build_stable_core_async(self, mcp_snippet, skills_snippet, subagents_snippet) -> str:
        """Async variant: same stable-prefix assembly, but file reads (rules,
        and the role definition on cache miss) happen on a worker thread."""
        from core.role_registry import RoleRegistry

        rules_snippet = await get_rules_snippet_async(role=self.role, cwd=self.cwd)
        role_def = None
        if self._stable_core_cached(rules_snippet, mcp_snippet, skills_snippet, subagents_snippet) is None:
            role_def = await asyncio.to_thread(
                RoleRegistry.get_instance().get_role, self.role, self.cwd or os.getcwd()
            )
        return self._assemble_stable_core(
            rules_snippet, mcp_snippet, skills_snippet, subagents_snippet, role_def
        )

    def build_tools(self) -> List[Dict[str, Any]]:
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
                t.get("function", {}).get("name", "").lower() == "invoke_subagent"
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
        _TOOLS_CACHE.put(key, sorted_tools)
        return list(sorted_tools)
