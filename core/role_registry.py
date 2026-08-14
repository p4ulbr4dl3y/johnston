import os
from typing import Any, Dict, List, Optional, Tuple

from core.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.defaults.tools import SUBAGENT_EXCLUDED_TOOLS, WRITE_TOOLS
from core.infrastructure.runtime.frontmatter import parse_csv_list, parse_frontmatter
from core.markdown_scanner import MarkdownScannerCache
from tools.base import format_tool_error

# Legacy scope aliases -> canonical names. Kept indefinitely so existing role
# files (and persisted sessions) keep working after the rename.
_SCOPE_ALIASES = {
    "main_only": "main",
    "subagent_only": "subagent",
}


def normalize_role_scope(scope: str) -> str:
    """Normalize a role scope value to its canonical short name."""
    clean = (scope or "").strip().lower() or "any"
    return _SCOPE_ALIASES.get(clean, clean)


class AgentRole:
    """Unified definition for agent execution roles and modes."""

    def __init__(
        self,
        key: str,
        name: str = "",
        description: str = "",
        prompt: str = "",
        read_only: bool = False,
        disallowed_tools: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None,
        model: str = "",
        provider: str = "",
        scope: str = "any",
        source: str = "builtin",
    ):
        self.key = key.lower().strip()
        self.name = name or self.key.capitalize()
        self.description = description
        self.prompt = prompt or ""
        self.read_only = read_only
        self.disallowed_tools = [t.strip() for t in (disallowed_tools or [])]
        self.allowed_tools = [t.strip() for t in (allowed_tools or [])]
        self.model = model
        self.provider = (provider or "").strip().lower()
        self.scope = normalize_role_scope(scope)
        self.source = source

    @property
    def system_prompt(self) -> str:
        return self.prompt

    def is_tool_allowed(self, tool_name: str) -> Optional[str]:
        """Returns an error string if this role disables tool_name, else None."""
        return role_tool_error(self, tool_name)


# Single source of truth for role/mode tool-policy checks. Used by
# role_tool_error, AgentRole.is_tool_allowed, roles/tools, and prompt_builder so
# disallowed, read_only, allowed_tools, and subagent exclusions are honored in
# one place.
def _tool_policy_result(
    role_def: Any, tool_name: str, is_subagent: bool = False
) -> Tuple[bool, Optional[str]]:
    """Evaluate a tool call against a role or mode object.

    Returns (allowed, reason). reason is None when allowed. Works with both
    AgentRole instances and duck-typed mode objects exposing disallowed_tools,
    read_only, allowed_tools, and name attributes. When ``is_subagent`` is set,
    subagent-excluded tools are always denied.
    """
    if not tool_name:
        return True, None
    clean = (tool_name or "").strip().lower()
    if clean.startswith("functions."):
        clean = clean.split(".", 1)[1]

    try:
        from tools.registry import normalize_tool_name

        resolved = normalize_tool_name(clean)
    except Exception:
        resolved = clean

    if is_subagent and (clean in SUBAGENT_EXCLUDED_TOOLS or resolved in SUBAGENT_EXCLUDED_TOOLS):
        return False, format_tool_error(f"tool '{clean}' disabled for subagent roles")

    name = getattr(role_def, "name", "Role")
    disallowed = [t.lower() for t in (getattr(role_def, "disallowed_tools", []) or [])]
    if clean in disallowed or resolved in disallowed:
        return False, format_tool_error(f"tool '{clean}' disabled in {name} role")

    if getattr(role_def, "read_only", False) and (clean in WRITE_TOOLS or resolved in WRITE_TOOLS):
        return False, format_tool_error(f"tool '{clean}' disabled in read-only {name} role")

    allowed = [t.lower() for t in (getattr(role_def, "allowed_tools", []) or [])]
    if allowed and clean not in allowed and resolved not in allowed:
        return False, format_tool_error(f"tool '{clean}' not in allowed tools list for {name} role")

    return True, None


# Canonical predicate for "is this tool allowed for the role?". Returns None when
# allowed, or an error string describing the denial.
def role_tool_error(role_def: Any, tool_name: str, is_subagent: bool = False) -> Optional[str]:
    """Return an error string if role_def denies tool_name, else None."""
    if not role_def:
        return None
    _, reason = _tool_policy_result(role_def, tool_name, is_subagent=is_subagent)
    return reason


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
            "### Overview\n"
            "You are an orchestrator: you plan, delegate bounded subtasks to subagents, "
            "coordinate them, and integrate their results. You retain full tool access and "
            "decide autonomously when to spawn subagents and when to do the work directly.\n\n"
            "### The Core Tradeoff: Parallelism vs. Shared Context\n"
            "Parallelism wins on wall-clock time but can lose on tokens. The real cost of "
            "delegation is NOT the spawn itself — it is (a) the price of transferring enough "
            "context to each subagent, and (b) duplicated re-learning. If every subagent would "
            "independently hit the same framework/harness quirks, that debugging cost is paid once "
            "per subagent instead of once total. Decide delegation by TYPE OF WORK, not just "
            "by independence.\n\n"
            "### Decision Rule: Subagents Are A Tool, Not A Default\n"
            "1. Do the work directly when a task is small, tightly coupled, or touches a "
            "single area — spawning a subagent would only add overhead and context cost.\n"
            "2. Keep work that requires iterative framework/harness debugging with yourself. "
            "One head with already-accumulated context breaks a quirk once; N subagents in N "
            "branches each re-derive it. Async/cancellation flows, UI event handlers, and "
            "complex mocking are prime candidates to keep local.\n"
            "3. Delegate mechanical, repeatable, and context-cheap work: isolated print/CLI "
            "functions, redirect_stdout tests, simple mocks, independent research, and "
            "independent experiments. These parallelize cleanly and transfer cheaply.\n"
            "4. For analysis or reconnaissance, delegate to `subagent_type` 'explorer'. "
            "For isolated execution, delegate to `subagent_type` 'worker'. "
            "`branch` is required on every `invoke_subagent`; pass the current branch name "
            "unless the subtask should run in an isolated worktree.\n\n"
            "### Orchestration Rules\n"
            "1. Decompose first, then delegate: lay out the subtasks and dependencies "
            "before launching anything.\n"
            "2. Load the harness context BEFORE delegating. First (yourself or via an "
            "'explorer' subagent) discover the framework patterns, idioms, and quirks that "
            "subtasks will depend on. Hand subtasks ready-made idioms instead of making them "
            "re-learn the harness. This is the single biggest token saver.\n"
            f"3. Respect the concurrency cap (max {MAX_CONCURRENT_SUBAGENTS} concurrent subagents). Launch only as "
            "many subagents in parallel as is useful; do not saturate the queue blindly.\n"
            "4. NEVER spawn a subagent for work the main agent can finish faster directly. "
            "If subtasks share significant context, prefer doing them serially yourself over "
            "duplicating that context across N subagents.\n"
            "5. DO NOT chain subagents recursively or delegate delegation — subagents "
            "cannot spawn subagents. You are the only orchestrator.\n"
            "6. Use `manage_subagent(action='status')` sparingly to check on background work; "
            "never poll it in a loop. End your turn and let notifications arrive instead.\n\n"
            "### Integration Rules\n"
            "1. Collect and synthesize each subagent's <task_result> into a coherent "
            "response; do not dump raw results at the user.\n"
            "2. When subagents return on isolated branches, review the diffs, then ask the "
            "user (via `ask_user`) before merging (`git merge <branch>`) and before deleting "
            "subagent-created branches (`git branch -D <branch>`).\n"
            "3. Verify integrated work with tests/linters before declaring completion. Pay "
            "special attention to regression in the shared harness (async workers, mocking "
            "read-only properties, UI event handlers) — that is the most expensive place for "
            "subagents to break silently.\n"
            "4. For work you do directly rather than delegate, follow the execution rules of the `worker` role."
        ),
        scope="main",
        source="builtin",
    ),
}


class RoleRegistry:
    """Unified registry managing agent execution roles."""

    _instance: Optional["RoleRegistry"] = None

    def __init__(self):
        self.roles: Dict[str, AgentRole] = dict(BUILTIN_ROLES)
        self.current_project_dir: Optional[str] = None
        self._cache = MarkdownScannerCache(subpath="roles")

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
            )
        except Exception:
            return None
