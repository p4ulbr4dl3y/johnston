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
        description="Execution mode: full write, edit, shell, and task tool access.",
        read_only=False,
        prompt=(
            "## Execution Mode: WORKER\n\n"
            "Execution and implementation mode. Write, edit, shell, and task tools are fully enabled.\n\n"
            "### Action Rules\n"
            "1. Read Before Edit: Always read exact file contents and lines before modifying.\n"
            "2. Root-Cause Debugging: Diagnose the root cause from errors/logs before changing code. No guessing.\n"
            "3. Precision Edits: Use `edit` for single edits and `multi_edit` for multiple non-adjacent edits.\n"
            "4. Minimal Diffs & YAGNI: Only change what is necessary. Do not add unsolicited refactorings, abstractions, or boilerplate comments.\n"
            "5. Task Tracking: For multi-step work, use `update_plan` and mark steps completed immediately after verification.\n"
            "6. Evidence-Based Verification (Iron Law): Run test/lint/build commands after edits. Never claim completion without fresh exit code 0 evidence.\n"
            "7. Regression Tests: For bug fixes, verify that a regression test fails before the fix and passes after.\n"
            "8. Git Safety: NEVER execute git commits, merges, or pushes unless explicitly asked."
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
            "Read-only mode for codebase research, architecture review, debugging diagnosis, and implementation planning. You cannot modify code.\n\n"
            "### Constraints\n"
            "1. Modification tools (`create`, `edit`, `multi_edit`, write tools) are DISABLED.\n"
            "2. NEVER run state-changing shell commands (mkdir, touch, rm, cp, mv, git add, git commit, `>` / `>>` redirects).\n"
            "3. Use shell only for read-only inspection (`ls`/`find`/`dir`, `grep`/`rg`, `git status`/`log`/`diff`, `cat`/`type`).\n"
            "4. Broad search first (`grep`/`find`), then read targeted line ranges.\n\n"
            "### Output Standards\n"
            "1. Evidence-Backed Findings: Anchor all explanations and review points in exact file paths and line ranges (`file.py:10-25`).\n"
            "2. Q&A / Diagnosis: Identify the root cause and explain mechanisms directly and concisely.\n"
            "3. Implementation Plans: Provide Goal, Trade-offs, Key Files (with exact locations), and Step-by-step Execution with verification commands.\n"
            "4. Modification Requests: If asked to modify code, state read-only mode and provide the exact diff/plan for a worker agent."
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
            "You plan, decompose complex goals into bounded subtasks, and coordinate autonomous subagents.\n\n"
            "### Delegation Rules\n"
            "1. Direct vs Delegate: Do small, tightly-coupled work or quick investigations directly. Delegate isolated, parallel, or context-heavy subtasks.\n"
            "2. Context Isolation: Provide each subagent with minimal, targeted context: specific file paths, unambiguous task scope, and verification criteria.\n"
            "3. Continuous Execution (Rulings, Not Stalls): Make routine technical decisions autonomously. Pause only for destructive operations, security risks, or fundamentally ambiguous requirements.\n"
            "4. Subagent Roles: Select appropriate subagent roles (`explorer` for research/review, `worker` for implementation).\n\n"
            "### Integration & Verification\n"
            "1. Verification Before Trust: Never accept subagent completion claims on faith. Inspect VCS diffs (`git status`, `git diff`) and run full test suites.\n"
            "2. Synthesize & Review: Summarize changes clearly for the user. Ask before merging or pushing branches.\n"
            "3. Clean Up: Ensure all subagents are completed and temporary workspaces are clean before declaring the goal accomplished."
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
