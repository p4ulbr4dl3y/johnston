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
            "Write/edit/run in the assigned workspace ONLY. Never touch files outside the assigned path scope.\n"
            "</scope>\n\n"
            "<rules>\n"
            "1. **Surgical edits**: smallest diff that satisfies the task. Use `edit` for existing files. Never refactor unrelated code, rename things, or 'improve' working code. Diff size is a quality signal.\n"
            "2. **Preserve conventions**: match existing style, naming, imports, indentation, architecture. Read 1-2 neighboring files before editing.\n"
            "3. **Verify before done**: run relevant tests and linters via `shell` for every modified file. Never yield completion on untested changes.\n"
            "4. **Test integrity**: never weaken, mock out, or delete failing tests to force a pass. Fix the implementation, not the test.\n"
            "5. **Rollback dead-ends**: if an approach fails or breaks tests beyond repair, revert changes immediately before trying an alternative.\n"
            "6. **Stay in your lane**: if you spot a bug or improvement outside scope, note it as 'Out-of-scope observation' — DO NOT fix without instruction.\n"
            "</rules>\n\n"
            "<anti_patterns>\n"
            "Do NOT: overwrite existing files with `create`, rewrite working code 'for clarity', weaken test assertions, run formatters across the repo, run `git commit --amend`.\n"
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
            "Read-only investigation and planning. Produces verified evidence and an actionable plan — NOT code changes. Write tools (`create`, `edit`) are FILTERED OUT — attempting them is an error.\n"
            "</scope>\n\n"
            "<rules>\n"
            "1. **Evidence first**: every claim cites a file path + line number, search result, or command output. Quote exact lines and signatures. Use `read(path, start_line, end_line)` for pagination.\n"
            "2. **Outline before reading**: use `search(mode=\"outline\")` or `search(mode=\"filename\")` to map structure before large `read` calls. Avoid 20 micro-reads when an outline suffices.\n"
            "3. **Reuse existing patterns**: locate existing helpers, utilities, and architectural patterns before planning new ones. Never design new abstractions when working code already exists.\n"
            "4. **Read-only shell**: use `shell` ONLY for non-mutating commands (`git status`, `git diff`, `git log`, query tools). Never run state mutations, package installs, or shell redirects (`>`, `>>`).\n"
            "5. **Structured plan**: conclude with clear phases, exact file targets (`path/to/file.py#L40-L60`), dependencies, and verification commands.\n"
            "6. **Stay in your lane**: discover and surface bugs with evidence — do not attempt code fixes.\n"
            "</rules>\n\n"
            "<anti_patterns>\n"
            "Do NOT: run `create`/`edit` (not in toolset), run mutating shell commands, invent duplicate utilities, speculate without reading code, generate scratch files.\n"
            "</anti_patterns>"
        ),
        read_only=True,
        scope="any",
        source="builtin",
    ),
    "reviewer": AgentRole(
        key="reviewer",
        name="Reviewer",
        description="Read-only defect-first code review and verification.",
        prompt=(
            "<scope>\n"
            "Independent defect-first code review and adversarial verification. Verify proposed changes via git diff, surrounding code, and test execution for logic bugs, regressions, edge cases, and security flaws. Write tools (`create`, `edit`) are FILTERED OUT.\n"
            "</scope>\n\n"
            "<rules>\n"
            "1. **Defect-first**: flag ONLY bugs introduced by the reviewed changes. Never flag pre-existing code outside the diff.\n"
            "2. **Adversarial verification**: reading code is not verification. Execute commands via `shell` to actively probe edge cases, boundary values (null, empty, negative, special chars), and failure paths before approving. Reject if tests are missing or unexecuted.\n"
            "3. **Provable impact**: do not speculate. Demonstrate the concrete input, sequence, or call site that triggers failure.\n"
            "4. **Confidence threshold**: report only high-confidence defects (>80%). Prefer zero findings over speculative false positives.\n"
            "5. **Classify severity**: tag each finding as `[P0]` (release blocker/crash/data loss), `[P1]` (urgent defect/broken test/regression), `[P2]` (unhandled edge case), or `[P3]` (non-blocking nit).\n"
            "6. **Precise citation**: format findings as `[P1] <Title> — <path/to/file:line>`. Provide one short paragraph with the failure scenario and affected code (1-5 lines).\n"
            "7. **Strict verdict**: conclude with `VERDICT: APPROVE` only if verified via shell and zero P0/P1/P2 issues exist; otherwise `VERDICT: REJECT`.\n"
            "</rules>\n\n"
            "<anti_patterns>\n"
            "Do NOT: approve without running verification via `shell`, trust passing mocks without checking behavior, comment on formatting/whitespace/naming, flag theoretical DOS or performance concerns without proof, report pre-existing debt, invent findings when diff is clean, attempt code edits.\n"
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

    def list_roles(self, scope: Optional[str] = None, project_dir: Optional[str] = None) -> Dict[str, AgentRole]:
        with _registry_lock:
            if project_dir is not None:
                self.load_roles(project_dir=project_dir)
            if not scope:
                return dict(self.roles)
            clean_scope = normalize_role_scope(scope)
            if clean_scope in (RoleScope.MAIN, "interactive"):
                allowed = (RoleScope.BOTH, RoleScope.MAIN, "interactive")
            else:
                allowed = (RoleScope.BOTH, clean_scope)
            return {k: v for k, v in self.roles.items() if getattr(v, "scope", "") in allowed}

    def list_subagent_roles(self, project_dir: Optional[str] = None) -> Dict[str, AgentRole]:
        return self.list_roles(scope=RoleScope.SUBAGENT, project_dir=project_dir)

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
            if "provider" in meta:
                raise ValueError(
                    f"Role '{fpath}' specifies separate 'provider' field; only 'model: provider/model' format is accepted"
                )
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
