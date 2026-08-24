import os
from typing import Callable, Dict, Optional

from core.domain.policies.role_policy import (
    AgentRole,
    RoleScope,
    RoleSource,
    normalize_role_scope,
)
from core.infrastructure.runtime.frontmatter import parse_csv_list, parse_frontmatter
from core.infrastructure.runtime.markdown_scanner import MarkdownScannerCache

BUILTIN_ROLES: Dict[str, AgentRole] = {
    "worker": AgentRole(
        key="worker",
        name="Worker",
        description="Execution mode: creation, editing, and shell command execution.",
        prompt=(
            "## Execution Mode: WORKER\n\n"
            "1. Surgical Execution: Modify only what the task strictly requires. NEVER make unsolicited changes, speculative additions, or touch unrelated items.\n"
            "2. State Preservation: Preserve existing structure, conventions, and functional integrity unless explicitly instructed to alter them.\n"
            "3. Safety: NEVER perform irreversible destruction or accidental data loss; operate strictly within the assigned task boundaries."
        ),
        scope="any",
        source="builtin",
    ),
    "explorer": AgentRole(
        key="explorer",
        name="Explorer",
        description="Read-only mode for information gathering, research, analysis, and action planning.",
        prompt=(
            "## Execution Mode: EXPLORER\n\n"
            "1. Read-Only: Strictly read-only mode. NEVER execute state-changing actions, mutations, or write operations.\n"
            "2. Evidence-Backed: Anchor all findings and diagnoses in exact sources, data, or references.\n"
            "3. Action Plans: When planning, provide Goal, Trade-offs, Key Dependencies, and Step-by-step Execution with verification criteria.\n"
            "4. Mutation Requests: When requested to modify state, decline mutation and provide the actionable execution plan instead."
        ),
        disallowed_tools=[
            "create",
            "edit",
        ],
        scope="any",
        source="builtin",
    ),
}


class RoleRegistry:
    """Unified registry managing agent execution roles."""

    _instance: Optional["RoleRegistry"] = None

    def __init__(self, tool_name_normalizer: Optional[Callable[[str], str]] = None):
        self.tool_name_normalizer = tool_name_normalizer
        self.roles: Dict[str, AgentRole] = dict(BUILTIN_ROLES)
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
            roles: Dict[str, AgentRole] = dict(BUILTIN_ROLES)
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

        builtins = []
        globals_list = []
        project_list = []

        for role in subagent_roles.values():
            tools_info = f" (Tools: {', '.join(role.allowed_tools)})" if role.allowed_tools else ""
            prov_info = f" (provider: {role.provider})" if role.provider else ""
            desc = f": {role.description}" if role.description else ""
            line = f"- `{role.key}`{desc}{tools_info}{prov_info}"
            if role.source == RoleSource.BUILTIN:
                builtins.append(line)
            elif role.source == RoleSource.GLOBAL:
                globals_list.append(line)
            elif role.source == RoleSource.PROJECT:
                project_list.append(line)

        lines = ["## Subagents (use as `type` in `invoke_subagent`)"]
        if builtins:
            lines.append("\n### Builtin")
            lines.extend(builtins)
        if globals_list:
            lines.append("\n### Global (`~/.johnston/roles/<name>.md`)")
            lines.extend(globals_list)
        if project_list:
            lines.append("\n### Project (`.johnston/roles/<name>.md`)")
            lines.extend(project_list)

        return "\n".join(lines)

    def _parse_md_role(self, fpath: str, source: str) -> Optional[AgentRole]:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                return None

            base_key = os.path.splitext(os.path.basename(fpath))[0]
            meta, prompt = parse_frontmatter(raw)
            prompt = prompt.strip()

            key = meta.get("key") or meta.get("name") or base_key
            name = meta.get("name") or key.capitalize()
            desc = meta.get("description", "")
            model = meta.get("model", "")
            provider = meta.get("provider", "")
            scope = meta.get("scope", "any")

            disallowed_tools = parse_csv_list(meta.get("disallowed_tools"))
            allowed_tools = parse_csv_list(meta.get("allowed_tools"))

            return AgentRole(
                key=key,
                name=name,
                description=desc,
                prompt=prompt,
                disallowed_tools=disallowed_tools,
                allowed_tools=allowed_tools,
                model=model,
                provider=provider,
                scope=scope,
                source=source,
                tool_name_normalizer=self.tool_name_normalizer,
            )
        except Exception:
            return None
