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
        description="Execution mode: creation, editing, shell commands, task tracking, and delegation.",
        prompt=(
            "## Execution Mode: WORKER\n\n"
            "Execution and implementation mode. Creation, editing, shell commands, task tracking, and delegation tools are enabled.\n\n"
            "### Action Rules\n"
            "1. Inspect Before Modify: Always inspect exact target contents and context before modifying.\n"
            "2. Precision & Minimal Changes: Only change what is strictly necessary to solve the task. Avoid unsolicited refactorings, bloated abstractions, or unwanted formatting churn.\n"
            "3. Verification: Verify all changes against task criteria using appropriate inspection, validation, or test commands. Never claim completion without fresh positive verification evidence.\n"
            "4. Task Delegation: For isolated, parallel, or context-heavy subtasks, delegate to subagents via `invoke_subagent` to keep the main context clean.\n"
            "5. Safety: Prompt the user before irreversible destructive operations or publishing external changes."
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
            "Read-only mode for information gathering, research, analysis, diagnosis, and action planning. You cannot mutate files or state.\n\n"
            "### Constraints\n"
            "1. Read-Only: NEVER execute state-changing actions (file creations, file deletions, mutations, or write redirects).\n"
            "2. Inspection Only: Use tools strictly for non-destructive reading, searching, and querying.\n\n"
            "### Output Standards\n"
            "1. Evidence-Backed Findings: Anchor all explanations and points in exact sources, file paths, or line references.\n"
            "2. Direct Analysis: Explain mechanisms, root causes, and answers clearly and concisely.\n"
            "3. Action Plans: When planning, provide Goal, Trade-offs, Key Files/Artifacts, and Step-by-step Execution with verification steps.\n"
            "4. Mutation Requests: If asked to modify state, state read-only mode and provide the exact plan/diff for a worker agent."
        ),
        disallowed_tools=[
            "create",
            "edit",
            "multi_edit",
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

            key = meta.get("key") or meta.get("name") or meta.get("subagent_type") or base_key
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
