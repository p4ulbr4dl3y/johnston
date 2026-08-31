import copy
import logging
import os
from typing import Callable, Dict, Optional

from core.domain.policies.role_policy import (
    AgentRole,
    RoleScope,
    normalize_role_scope,
)
from core.infrastructure.runtime.frontmatter import parse_csv_list, parse_frontmatter
from core.infrastructure.runtime.markdown_scanner import MarkdownScannerCache

logger = logging.getLogger(__name__)

BUILTIN_ROLES: Dict[str, AgentRole] = {
    "worker": AgentRole(
        key="worker",
        name="Worker",
        description="Execution mode: creation, editing, and shell command execution.",
        prompt=(
            "1. Surgical Edits: Modify only what the task strictly requires. NEVER do unrelated refactoring or touch unrelated files.\n"
            "2. Preservation: Maintain existing code conventions, architecture, and comments.\n"
            "3. Verification: Run tests/linters before finishing to ensure changes do not break the codebase."
        ),
        scope="any",
        source="builtin",
    ),
    "explorer": AgentRole(
        key="explorer",
        name="Explorer",
        description="Read-only mode for information gathering, research, analysis, and action planning.",
        prompt=(
            "1. Read-Only: Strictly exploration and analysis. NEVER attempt to create, modify, or delete files.\n"
            "2. Evidence: Anchor all findings in exact file paths, line numbers, and search results.\n"
            "3. Actionable Plans: When proposing solutions, specify target files, required changes, and verification steps."
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
        self.load_roles(project_dir=project_dir)
        subagent_roles = self.list_subagent_roles()
        if not subagent_roles:
            return ""

        from core.infrastructure.runtime.prompt_markdown import format_subagents_markdown

        return format_subagents_markdown(list(subagent_roles.values()))

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
            name = meta.get("name") or key.capitalize()
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
