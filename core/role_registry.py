import os
from typing import Callable, Dict, Optional

from core.domain.policies.role_policy import (
    AgentRole,
    normalize_role_scope,
)
from core.infrastructure.runtime.frontmatter import parse_csv_list, parse_frontmatter
from core.infrastructure.runtime.markdown_scanner import MarkdownScannerCache

BUILTIN_ROLES: Dict[str, AgentRole] = {
    "worker": AgentRole(
        key="worker",
        name="Worker",
        description="Execution mode: full write, edit, shell, and task tool access.",
        read_only=False,
        prompt=(
            "## Execution Mode: WORKER\n\n"
            "Execution and implementation mode. Write, edit, shell, and task tools are fully enabled.\n\n"
            "### Action Rules\n"
            "1. Read Before Edit: Always read file contents before modifying.\n"
            "2. Precision Edits: Use `edit` for single edits and `multi_edit` for multiple non-adjacent edits.\n"
            "3. Minimal Comments: Do not add unnecessary comments unless requested.\n"
            "4. Task Planning: For multi-step work, use `update_plan` and mark steps completed promptly.\n"
            "5. Verification: Run tests or linters after editing to verify changes.\n"
            "6. Scope Discipline (YAGNI): Don't add features or refactorings beyond what was asked; three similar lines are better than a premature abstraction.\n"
            "7. No Unsolicited Commits: NEVER execute git commits unless explicitly asked."
        ),
        scope="any",
        source="builtin",
    ),
    "explorer": AgentRole(
        key="explorer",
        name="Explorer",
        description="Read-only Q&A, codebase research, and planning role.",
        read_only=True,
        prompt=(
            "## Execution Mode: EXPLORER\n\n"
            "Read-only mode for Q&A, codebase research, code explanation, architecture review, and implementation planning. You cannot modify code.\n\n"
            "### Constraints\n"
            "1. Modification tools (`create`, `edit`, `multi_edit`, write tools) are DISABLED.\n"
            "2. NEVER run state-changing shell commands (mkdir, touch, rm, cp, mv, git add, git commit, `>` / `>>` redirects).\n"
            "3. Use shell only for read-only inspection (`ls`/`find`/`dir`, `grep`/`rg`, `git status`/`log`/`diff`, `cat`/`type`).\n"
            "4. Broad search first (`grep`/`find`), then inspect targeted files. Prefer parallel reads for multiple files.\n\n"
            "### Response\n"
            "1. Q&A / Explanation: answer directly, clearly, concisely — no forced plan.\n"
            "2. Planning request: give Goal, Trade-offs, Key Files (3-5), Execution Steps.\n"
            "3. If asked to make changes: state you are in read-only mode and cannot apply them."
        ),
        disallowed_tools=[
            "create",
            "edit",
            "multi_edit",
            "write_to_file",
            "replace_file_content",
            "multi_replace_file_content",
        ],
        scope="any",
        source="builtin",
    ),
    "orchestrator": AgentRole(
        key="orchestrator",
        name="Orchestrator",
        description="Orchestrator role (primary agent only): plan and delegate bounded subtasks",
        read_only=False,
        prompt=(
            "## Execution Mode: ORCHESTRATOR\n\n"
            "You plan, decompose goals into bounded subtasks, and coordinate autonomous subagents.\n\n"
            "### Delegation Rules\n"
            "1. Do work directly for small, tightly-coupled tasks or iterative debugging.\n"
            "2. Delegate isolated, parallel, or context-cheap tasks (independent research, isolated modules/tests).\n"
            "3. Provide clear context, boundaries, and expected output in each subagent prompt.\n"
            "4. For batch subagents sharing instructions, define a project role (`.johnston/roles/<name>.md`, see johnston-guide) instead of duplicating long system prompts in each task.\n\n"
            "### Integration Rules\n"
            "1. Synthesize subagent results into a coherent response.\n"
            "2. Review diffs and ask the user before merging isolated branches.\n"
            "3. Verify integrated changes with tests/linters before finishing.\n"
            "4. For direct work, follow standard engineering practices."
        ),
        scope="main",
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
        return {k: v for k, v in self.roles.items() if v.scope in ("any", clean_scope)}

    def list_subagent_roles(self) -> Dict[str, AgentRole]:
        return {k: v for k, v in self.roles.items() if v.scope in ("any", "subagent")}

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
            if role.source == "builtin":
                builtins.append(line)
            elif role.source == "global":
                globals_list.append(line)
            elif role.source == "project":
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
            read_only_val = str(meta.get("read_only", "false")).lower() in ("true", "1", "yes")
            model = meta.get("model", "")
            provider = meta.get("provider", "")
            scope = meta.get("scope", "any")

            disallowed_tools = parse_csv_list(meta.get("disallowed_tools"))
            allowed_tools = parse_csv_list(meta.get("tools")) or parse_csv_list(meta.get("allowed_tools"))

            return AgentRole(
                key=key,
                name=name,
                description=desc,
                prompt=prompt,
                read_only=read_only_val,
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
