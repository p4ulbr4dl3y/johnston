"""PromptBuilder — composite system prompt and tool definitions for MCP, Skills and agent role.

Concern split (see the sibling modules):

- ``git_info``: git branch detection + per-directory TTL cache.
- ``project_rules``: project instruction files (AGENTS.md, .cursor/rules, ...) and
  rules-snippet assembly with mtime-based cache invalidation.

This module keeps the ``PromptBuilder`` class and re-exports the moved public
API so every import site (``johnston.core.infrastructure.llm.base.tools``, widgets, tests) works
unchanged.
"""

import asyncio
import datetime
import hashlib
import json
import os
import platform
from typing import Any, Dict, List, Optional

from johnston.core.application.generation.git_info import (
    _GIT_INFO_CACHE,  # noqa: F401  (re-exported for tests/monkeypatch targets)
    _GIT_INFO_CACHE_TTL,  # noqa: F401  (re-exported for tests/monkeypatch targets)
    _compute_git_info,  # noqa: F401  (re-exported for tests/monkeypatch targets)
    get_git_info,
    get_git_info_async,
)
from johnston.core.application.generation.project_rules import (
    _PROJECT_INSTR_CACHE_MAX,  # noqa: F401  (re-exported for tests)
    _PROJECT_INSTRUCTION_CACHE,  # noqa: F401  (re-exported for tests)
    INSTRUCTION_FILES,
    get_project_instruction_rules,  # noqa: F401  (re-exported public API)
    get_project_instructions_snippet,  # noqa: F401  (re-exported public API)
    get_rules_snippet,
    get_rules_snippet_async,
)
from johnston.core.application.skills.manager import get_skill_manager
from johnston.core.domain.defaults.prompts import (
    CODEBASE_NAVIGATION_SNIPPET,
    DEFAULT_SYSTEM_PROMPT,
    SUBAGENT_DEFAULT_SYSTEM_PROMPT,
    SUBAGENT_WORKTREE_PROMPT,
    TOOL_OUTPUT_FORMAT_SNIPPET,
    WORKTREE_PROMPT,
)
from johnston.core.infrastructure.runtime.lru import LruCache
from johnston.core.infrastructure.runtime.xml_utils import escape_xml

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "SUBAGENT_DEFAULT_SYSTEM_PROMPT",
    "SUBAGENT_WORKTREE_PROMPT",
    "WORKTREE_PROMPT",
    "PromptBuilder",
    "INSTRUCTION_FILES",
]

_STABLE_CORE_CACHE_MAX = 256
_TOOLS_CACHE_MAX = 32

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
        mode: Optional[Any] = None,
    ):
        self.base_system_prompt = base_system_prompt
        self.base_tools = list(base_tools or [])
        self.role = role
        self.allow_task = allow_task
        self.model_name = model_name
        self.cwd = os.path.realpath(cwd) if cwd else None
        if mode is not None:
            self.mode = mode
        else:
            from johnston.core.domain.policies.role_policy import AgentMode

            self.mode = AgentMode.SUBAGENT if is_subagent else AgentMode.INTERACTIVE
        self.is_subagent = self.mode.is_subagent
        self.subagent_schema = subagent_schema
        self.worktree_branch = worktree_branch
        if sandbox_enabled is not None:
            self.sandbox_enabled = bool(sandbox_enabled)
        elif self.role == "explorer":
            self.sandbox_enabled = True
        else:
            from johnston.core.infrastructure.config.config_helpers import load_sandbox_config

            self.sandbox_enabled = load_sandbox_config()

    def build_system_prompt(self) -> str:
        cwd = self.cwd or os.getcwd()
        from johnston.core.application.roles.role_registry import RoleRegistry
        from johnston.core.infrastructure.mcp import get_mcp_manager

        mcp_mgr = get_mcp_manager()
        mcp_snippet = mcp_mgr.get_system_prompt_snippet()
        from johnston.core.infrastructure.runtime.prompt_markdown import format_skills_markdown

        skills_snippet = format_skills_markdown(get_skill_manager(self.cwd).get_system_prompt_skills())
        subagents_snippet = (
            ""
            if not self.mode.is_interactive
            else RoleRegistry.get_instance().get_system_prompt_snippet(project_dir=cwd)
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
        from johnston.core.application.roles.role_registry import RoleRegistry
        from johnston.core.infrastructure.mcp import get_mcp_manager

        mcp_mgr = get_mcp_manager()
        mcp_snippet = await asyncio.to_thread(mcp_mgr.get_system_prompt_snippet)
        from johnston.core.infrastructure.runtime.prompt_markdown import format_skills_markdown

        skills_snippet = format_skills_markdown(
            await asyncio.to_thread(lambda: get_skill_manager(self.cwd).get_system_prompt_skills())
        )
        subagents_snippet = (
            ""
            if not self.mode.is_interactive
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
        """Identity/contract prefix of the stable core: base prompt and model-name substitution.

        The role block and worktree guidelines are intentionally NOT included:
        the role is represented in the stable-core cache key by role-definition identity,
        and worktree guidelines are appended at the end of stable core to preserve
        prompt prefix caching across branches.
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

        if "{compaction_ratio}" in sys_prompt:
            try:
                from johnston.core.infrastructure.config.settings import get_settings

                ratio = int(get_settings().llm.compaction_threshold_ratio * 100)
            except Exception:
                from johnston.core.domain.defaults.config import DEFAULT_COMPACTION_THRESHOLD_RATIO

                ratio = int(DEFAULT_COMPACTION_THRESHOLD_RATIO * 100)
            sys_prompt = sys_prompt.replace("{compaction_ratio}", str(ratio))

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
            CODEBASE_NAVIGATION_SNIPPET,
        )

    def _stable_core_cached(self, rules_snippet, mcp_snippet, skills_snippet, subagents_snippet) -> Optional[str]:
        """Cheap stable-core lookup using the registry's in-memory role state.

        No disk read: the registered roles are refreshed this turn on the main
        path by the subagents-snippet read and on every turn by
        ``build_tools`` -> ``get_role``, so the in-memory identity changes
        exactly when the on-disk role set changes.
        """
        from johnston.core.application.roles.role_registry import BUILTIN_ROLES, RoleRegistry

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
        - tool_io reference (so it caches once per session, not per turn)
        - codebase navigation
        - rules (project can override defaults; ordered project > global)
        - skills (rarely changes; read-once)
        - subagents (only main)
        - mcp (only when mcp tools are present)
        - worktree guidelines (if worktree_branch is active; placed at tail of stable core)
        """
        from johnston.core.application.roles.role_registry import RoleRegistry

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

        role_block = ""
        if getattr(role_def, "prompt", None) and not self.is_subagent and "<role" not in base:
            from johnston.core.application.roles.prompt import format_role_prompt

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

        # Insert tool_io_ref and codebase_navigation RIGHT AFTER identity/contract/role
        # so the model sees the wire-format and discovery rules before reading/searching.
        if TOOL_OUTPUT_FORMAT_SNIPPET:
            sys_prompt = f"{sys_prompt}\n\n{TOOL_OUTPUT_FORMAT_SNIPPET}"
        if CODEBASE_NAVIGATION_SNIPPET:
            sys_prompt = f"{sys_prompt}\n\n{CODEBASE_NAVIGATION_SNIPPET}"
        if rules_snippet:
            sys_prompt = f"{sys_prompt}\n\n{rules_snippet}"
        if skills_snippet:
            sys_prompt = f"{sys_prompt}\n\n{skills_snippet}"
        if subagents_snippet:
            sys_prompt = f"{sys_prompt}\n\n{subagents_snippet}"
        if mcp_snippet:
            sys_prompt = f"{sys_prompt}\n\n{mcp_snippet}"
        if self.worktree_branch and "<worktree>" not in sys_prompt:
            # Branch name is user-controlled and gets interpolated into the
            # system prompt. Escape it so a name containing literal
            # `</worktree>` cannot truncate the wrapper and inject
            # arbitrary content. Placed at the end of stable_core (before env_block)
            # to maximize prompt prefix cache hits across different branches.
            safe_branch = escape_xml(self.worktree_branch)
            sys_prompt = f"{sys_prompt}\n\n{WORKTREE_PROMPT.format(branch_name=safe_branch)}"

        _STABLE_CORE_CACHE.put(key, sys_prompt)
        return sys_prompt

    async def _build_stable_core_async(self, mcp_snippet, skills_snippet, subagents_snippet) -> str:
        """Async variant: same stable-prefix assembly, but file reads (rules,
        and the role definition on cache miss) happen on a worker thread."""
        from johnston.core.application.roles.role_registry import RoleRegistry

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
        from johnston.core.application.roles.role_registry import RoleRegistry
        from johnston.core.domain.policies.role_policy import role_tool_error
        from johnston.core.infrastructure.mcp import get_mcp_manager

        mcp_mgr = get_mcp_manager()
        mcp_tools = mcp_mgr.get_cached_tools()
        clean_mcp_tools = [{"type": t["type"], "function": t["function"]} for t in mcp_tools]

        base_tools_list = list(self.base_tools)
        role_def = RoleRegistry.get_instance().get_role(self.role, project_dir=self.cwd or os.getcwd())

        # Single role-tool policy (shared with roles/tools and role_registry).
        # mode passes the non-interactive excluded-tool check into the core policy.
        filtered_base = [
            t
            for t in base_tools_list
            if role_tool_error(role_def, t.get("function", {}).get("name", ""), mode=self.mode) is None
        ]
        if not self.allow_task:
            filtered_base = [
                t
                for t in filtered_base
                if t.get("function", {}).get("name", "").lower() not in ("invoke_subagent", "message_subagent")
            ]

        filtered_mcp = [
            t
            for t in clean_mcp_tools
            if role_tool_error(role_def, t.get("function", {}).get("name", ""), mode=self.mode) is None
        ]

        if (
            self.mode.is_interactive
            and self.allow_task
            and self.subagent_schema
            and role_tool_error(role_def, "invoke_subagent", mode=self.mode) is None
            and not any(
                t.get("function", {}).get("name", "").lower() == "invoke_subagent"
                for t in filtered_base
            )
        ):
            filtered_base.append(self.subagent_schema)

        if not self.mode.is_interactive:
            from johnston.core.application.roles.tools import _rebuild_tool

            filtered_base = [_rebuild_tool(t) for t in filtered_base]
            filtered_mcp = [_rebuild_tool(t) for t in filtered_mcp]

        # Built-ins win on name conflict with MCP tools.
        base_names = {t.get("function", {}).get("name", "") for t in filtered_base}
        filtered_mcp = [
            t for t in filtered_mcp if t.get("function", {}).get("name", "") not in base_names
        ]

        def _normalize_tool_schema(tool_dict: Dict[str, Any]) -> Dict[str, Any]:
            import copy

            t = copy.deepcopy(tool_dict)
            fn = t.get("function", {})
            params = fn.get("parameters", {})
            if isinstance(params, dict):
                # Preserve author's logical property order (e.g. target_file before content).
                # Only normalize/sort required fields deterministically.
                req = params.get("required")
                if isinstance(req, list):
                    try:
                        params["required"] = sorted(req, key=lambda item: (type(item).__name__, str(item)))
                    except Exception:
                        params["required"] = req
            return t

        # Identity key lets us reuse the last pre-sorted build when the tool
        # schemas (and role flags) are unchanged this turn, skipping the
        # per-schema deepcopy + re-sort.
        #
        # MCP tools: cheap generation-level fingerprint. The manager's
        # _generation counter is bumped on stop_all / project resets, and
        # clear_mcp_cache() drops clients entirely, so a restart or config
        # change always produces a new key. Per-tool content hashing is
        # avoided here because MCP schemas can be large (10-20 tools x big
        # schemas) and get_cached_tools() freshly formats the dicts every
        # call, so id()/content-based keys would defeat the cache entirely.
        def _mcp_names(tools: List[Dict[str, Any]]) -> tuple:
            return tuple(t.get("function", {}).get("name", "") for t in tools)

        # Base tools: static registry entries with small schemas; content
        # identity (name + sha256) keeps the cache correct when a registry
        # schema changes without a role change (non-interactive hardening also
        # rebuilds the shell dict every call, so referential identity would
        # permanently miss).
        def _base_tool_ident(t: Dict[str, Any]) -> tuple:
            if not isinstance(t, dict):
                return ("", str(t))
            fn = t.get("function") if isinstance(t.get("function"), dict) else {}
            name = fn.get("name", "") or t.get("name", "")
            try:
                content_str = json.dumps(t, sort_keys=True, default=repr)
            except Exception:
                content_str = repr(t)
            content_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()
            return (name, content_hash)

        key = (
            ("mcp", getattr(mcp_mgr, "_generation", 0), len(clean_mcp_tools), _mcp_names(clean_mcp_tools)),
            ("base", str(self.role), tuple(_base_tool_ident(t) for t in filtered_base)),
            self.mode,
            self.allow_task,
        )
        cached = _TOOLS_CACHE.get(key)
        if cached is not None:
            return list(cached)

        # Partitioned sort (built-ins prefix, followed by MCP tools).
        # Stable built-in prefix prevents MCP tool additions from invalidating KV cache.
        sorted_base = [_normalize_tool_schema(t) for t in filtered_base]
        sorted_base.sort(key=lambda t: (t.get("function", {}) or {}).get("name", ""))

        sorted_mcp = [_normalize_tool_schema(t) for t in filtered_mcp]
        sorted_mcp.sort(key=lambda t: (t.get("function", {}) or {}).get("name", ""))

        sorted_tools = sorted_base + sorted_mcp
        _TOOLS_CACHE.put(key, sorted_tools)
        return list(sorted_tools)
