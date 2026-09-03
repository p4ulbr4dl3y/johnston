import copy
import logging
import os
import threading
from typing import Any, Callable, Dict, Optional

from core.domain.policies.role_policy import (
    AgentRole,
    RoleScope,
    normalize_role_scope,
)
from core.infrastructure.runtime.frontmatter import parse_csv_list, parse_frontmatter
from core.infrastructure.runtime.markdown_scanner import MarkdownScannerCache

logger = logging.getLogger(__name__)

# RoleRegistry is a process-wide singleton shared by the sync UI path, the
# async agent loop and prompt-builder worker threads (asyncio.to_thread).
# load_roles mutates current_project_dir / roles / the scanner cache, so all
# state-mutating entry points serialize on this lock; the reentrant form lets
# get_role / get_system_prompt_snippet hold it across load_roles + read so a
# concurrent call for a different project dir cannot clobber in-flight state.
_registry_lock = threading.RLock()

BUILTIN_ROLES: Dict[str, AgentRole] = {
    "worker": AgentRole(
        key="worker",
        name="Worker",
        description="Execution mode: creation, editing, and shell command execution.",
        prompt=(
            "<scope>\n"
            "Write/edit/run in the assigned workspace ONLY. Never touch files outside the worktree or the assigned path scope.\n"
            "</scope>\n\n"
            "<rules>\n"
            "1. **Surgical edits**: smallest diff that satisfies the task. NEVER refactor unrelated code, fix unrelated bugs, rename things, or 'improve' working code. Diff size is a quality signal.\n"
            "2. **Preserve conventions**: match existing style, naming, imports, indentation, architecture. Read 1-2 neighboring files before editing if style is ambiguous. NEVER introduce new patterns/dependencies for a one-off task.\n"
            "3. **Verify before reporting done**: run the project's actual verification — tests, linters, type check, build. Cite names + exit codes in report. See `<tool_io_reference>` truncation/pagination — read the full file when needed.\n"
            "4. **Stay in your lane**: if you spot a bug or improvement outside scope, note it in the report as 'Out-of-scope observation' — DO NOT fix it. Parent decides what to do.\n"
            "5. **Worktree etiquette**: branch already exists; your changes auto-commit on completion. NEVER `git checkout/switch`, `git merge`, `git push`. NEVER `git commit` manually (autocommit runs once).\n"
            "6. **User rules win**: `<user_rules>` in this prompt override these defaults on conflict. Project rules > global rules > role defaults.\n"
            "</rules>\n\n"
            "<anti_patterns>\n"
            "Do NOT: rewrite working code 'for clarity', add unrequested error handling, change imports wholesale, run formatters across the repo, run `git commit --amend`, run interactive tools (`vim`, `less`, `python -i`, `fzf`, paginated `psql`).\n"
            "</anti_patterns>"
        ),
        scope="any",
        source="builtin",
    ),
    "explorer": AgentRole(
        key="explorer",
        name="Explorer",
        description="Read-only mode for information gathering, research, analysis, and action planning.",
        prompt=(
            "<scope>\n"
            "Read-only investigation. Produces evidence and a plan — NOT code changes. Write tools (`create`, `edit`) and `shell` are FILTERED OUT — attempting them is a tool-not-found error, not a soft hint to try anyway.\n"
            "</scope>\n\n"
            "<rules>\n"
            "1. **Evidence first**: every claim cites a file path + line number, search result, command output, or URL. 'I think X exists' is not a finding — read it and quote it. See `<tool_io_reference>` for read/pagination conventions; use `read(path, start_line, end_line)` for files > 800 lines.\n"
            "2. **No file modification**: do not even propose code edits in the report. Output a PLAN (target files + required changes + verification) for the parent to dispatch to a worker.\n"
            "3. **Map before you drill**: when exploring an unfamiliar area, list the top-level structure first (`ls`, `glob`, single `read` of `README.md`/`AGENTS.md`/`pyproject.toml`), then drill into the specific files the task names. Avoid 20 small reads when 2 broad ones suffice.\n"
            "4. **Quote, don't paraphrase**: paste the exact error string, exit code, line content, or function signature. Paraphrased findings get re-investigated by the parent.\n"
            "5. **Actionable plan format**: end the report with a numbered list — each item is one concrete next step the parent can dispatch (e.g. 'worker: rename `foo` to `bar` in `src/x.py#L10-L15`; verify: `pytest tests/test_x.py -k foo`').\n"
            "6. **Stay in your lane**: if you discover a bug, surface it in the report — do not attempt a fix. Parent decides scope.\n"
            "</rules>\n\n"
            "<anti_patterns>\n"
            "Do NOT: run `create`/`edit` (not in your toolset), run state-changing `shell` commands (`rm`, `mv`, `git commit`, package installs), speculate without reading, write speculative fixes to `.tmp/` thinking 'it's harmless' — it isn't, the report is the only deliverable.\n"
            "</anti_patterns>"
        ),
        read_only=True,
        scope="any",
        source="builtin",
    ),
}


def _fresh_builtins() -> Dict[str, AgentRole]:
    """Deep-copy the BUILTIN_ROLES template so registry instances never share
    mutable AgentRole objects with each other or with the module-level dict."""
    return {key: copy.deepcopy(role) for key, role in BUILTIN_ROLES.items()}


class RoleRegistry:
    """Unified registry managing agent execution roles."""

    _instance: Optional["RoleRegistry"] = None

    def __init__(self, tool_name_normalizer: Optional[Callable[[str], str]] = None):
        self.tool_name_normalizer = tool_name_normalizer
        self.roles: Dict[str, AgentRole] = _fresh_builtins()
        self._apply_normalizer(self.roles)
        self.current_project_dir: Optional[str] = None
        self._cache = MarkdownScannerCache(subpath="roles")

    def _apply_normalizer(self, roles: Dict[str, AgentRole]) -> None:
        if self.tool_name_normalizer is None:
            return
        for role in roles.values():
            role.tool_name_normalizer = self.tool_name_normalizer

    @classmethod
    def get_instance(cls) -> "RoleRegistry":
        if cls._instance is None:
            cls._instance = RoleRegistry()
        return cls._instance

    def load_roles(self, project_dir: Optional[str] = None, include_global: bool = True) -> Dict[str, AgentRole]:
        with _registry_lock:
            if project_dir is not None:
                self.current_project_dir = project_dir
            p_dir = self.current_project_dir or os.getcwd()

            def _build(_dirs, files):
                roles: Dict[str, AgentRole] = _fresh_builtins()
                for fpath, source in files:
                    role = self._parse_md_role(fpath, source)
                    if role:
                        roles[role.key] = role
                return roles

            self.roles = self._cache.get(
                project_dir=p_dir,
                include_global=include_global,
                build=_build,
            )
            self._apply_normalizer(self.roles)
            return self.roles

    def invalidate_cache(self) -> None:
        """Force the next load_roles/get_role/get_system_prompt_snippet to re-scan from disk."""
        self._cache.invalidate()

    def get_role(self, key: str, project_dir: Optional[str] = None) -> AgentRole:
        with _registry_lock:
            self.load_roles(project_dir=project_dir)
            key_lower = (key or "").lower().strip()
            if key_lower in self.roles:
                return self.roles[key_lower]
            return self.roles.get("worker") or BUILTIN_ROLES["worker"]

    def list_roles(self, scope: Optional[str] = None) -> Dict[str, AgentRole]:
        if not scope:
            return self.roles
        clean_scope = normalize_role_scope(scope)
        return {k: v for k, v in self.roles.items() if v.scope in (RoleScope.BOTH, clean_scope)}

    def list_subagent_roles(self) -> Dict[str, AgentRole]:
        return {k: v for k, v in self.roles.items() if v.scope in (RoleScope.BOTH, RoleScope.SUBAGENT)}

    def get_system_prompt_snippet(self, project_dir: Optional[str] = None) -> str:
        with _registry_lock:
            self.load_roles(project_dir=project_dir)
            subagent_roles = self.list_subagent_roles()
            if not subagent_roles:
                return ""

            # Pull max_concurrent from config so the subagent block carries the
            # real budget; fall back to the documented default if config is
            # unavailable (headless / early-init paths).
            try:
                from core.infrastructure.config.settings import get_settings

                max_concurrent = get_settings().subagents.max_concurrent
            except Exception:
                from core.domain.defaults.config import DEFAULT_MAX_CONCURRENT_SUBAGENTS

                max_concurrent = DEFAULT_MAX_CONCURRENT_SUBAGENTS

            from core.infrastructure.runtime.prompt_markdown import format_subagents_markdown

            return format_subagents_markdown(list(subagent_roles.values()), max_concurrent=max_concurrent)

    def _parse_md_role(self, fpath: str, source: str) -> Optional[AgentRole]:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                return None

            base_key = os.path.splitext(os.path.basename(fpath))[0]
            meta, prompt = parse_frontmatter(raw)
            prompt = prompt.strip()

            key = meta.get("key") or base_key
            name = meta.get("name") or key.replace("_", " ").replace("-", " ").title()
            desc = meta.get("description", "")
            model = meta.get("model", "")
            scope = meta.get("scope", "any")

            disallowed_tools = parse_csv_list(meta.get("disallowed_tools"))
            allowed_tools = parse_csv_list(meta.get("allowed_tools"))
            raw_ro = meta.get("read_only", False)
            if isinstance(raw_ro, str):
                read_only = raw_ro.strip().lower() in ("true", "1", "yes", "on")
            else:
                read_only = bool(raw_ro)

            return AgentRole(
                key=key,
                name=name,
                description=desc,
                prompt=prompt,
                disallowed_tools=disallowed_tools,
                allowed_tools=allowed_tools,
                model=model,
                scope=scope,
                source=source,
                tool_name_normalizer=self.tool_name_normalizer,
                read_only=read_only,
            )
        except Exception as exc:
            logger.warning("Skipping invalid role file %s: %s", fpath, exc)
            return None


def get_role_display_name(role_or_key: Any, project_dir: Optional[str] = None) -> str:
    """Return human-readable role name for a key, entity, or role definition."""
    if not role_or_key:
        return "Worker"
    if hasattr(role_or_key, "role_name") and role_or_key.role_name:
        return str(role_or_key.role_name)
    if hasattr(role_or_key, "name") and role_or_key.name:
        return str(role_or_key.name)
    if isinstance(role_or_key, str):
        registry = RoleRegistry.get_instance()
        registry.load_roles(project_dir=project_dir)
        key_lower = role_or_key.lower().strip()
        if key_lower in registry.roles:
            return registry.roles[key_lower].name
        return role_or_key.replace("_", " ").replace("-", " ").title()
    return "Worker"


def resolve_role_display_name(role: Any, project_dir: Optional[str] = None) -> str:
    """Resolve a human-readable role name, falling back to the default "worker" role.

    Shared by session and agent ``role_name`` properties. An empty/None role
    resolves to the worker display name ("Worker").
    """
    return get_role_display_name(role or "worker", project_dir=project_dir)
