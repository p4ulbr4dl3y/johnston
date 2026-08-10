import os
import time
from typing import Any, Dict, List, Optional, Tuple

from core.config import CONFIG_DIR
from core.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.defaults.subagents import DEFAULT_SUBAGENT_ROLES
from core.defaults.tools import WRITE_TOOLS
from core.frontmatter import iter_md_files, parse_csv_list, parse_frontmatter
from tools.base import format_tool_error


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
        allowed_shell_commands: Optional[List[str]] = None,
        workspace_allowlist: Optional[List[str]] = None,
        model: str = "",
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
        self.allowed_shell_commands = [c.strip() for c in (allowed_shell_commands or [])]
        self.workspace_allowlist = [p.strip() for p in (workspace_allowlist or [])]
        self.model = model
        self.scope = (scope or "any").lower().strip()
        self.source = source

    @property
    def system_prompt(self) -> str:
        return self.prompt

    def is_tool_allowed(self, tool_name: str) -> Optional[str]:
        """Returns an error string if this role disables tool_name, else None."""
        if not tool_name:
            return None
        clean = (tool_name or "").strip().lower()
        if clean.startswith("functions."):
            clean = clean.split(".", 1)[1]

        try:
            from tools.registry import normalize_tool_name

            resolved = normalize_tool_name(clean)
        except Exception:
            resolved = clean

        disallowed = [t.lower() for t in self.disallowed_tools]
        if clean in disallowed or resolved in disallowed:
            return format_tool_error(f"tool '{clean}' disabled in {self.name} role")

        if self.read_only and (clean in WRITE_TOOLS or resolved in WRITE_TOOLS):
            return format_tool_error(f"tool '{clean}' disabled in read-only {self.name} role")

        if self.allowed_tools:
            allowed = [t.lower() for t in self.allowed_tools]
            if clean not in allowed and resolved not in allowed:
                return format_tool_error(f"tool '{clean}' not in allowed tools list for {self.name} role")

        return None


# Helper function to validate tool call against role or mode object
def role_tool_error(role_def: Any, tool_name: str) -> Optional[str]:
    if not role_def:
        return None
    if isinstance(role_def, AgentRole):
        return role_def.is_tool_allowed(tool_name)

    disallowed = [t.lower() for t in (getattr(role_def, "disallowed_tools", []) or [])]
    clean = (tool_name or "").strip().lower()
    if clean.startswith("functions."):
        clean = clean.split(".", 1)[1]
    try:
        from tools.registry import normalize_tool_name

        resolved = normalize_tool_name(clean)
    except Exception:
        resolved = clean

    if clean in disallowed or resolved in disallowed:
        return format_tool_error(f"tool '{clean}' disabled in {getattr(role_def, 'name', 'Role')} role")
    if getattr(role_def, "read_only", False) and (clean in WRITE_TOOLS or resolved in WRITE_TOOLS):
        return format_tool_error(f"tool '{clean}' disabled in read-only {getattr(role_def, 'name', 'Role')} role")
    return None


BUILTIN_ROLES: Dict[str, AgentRole] = {
    "act": AgentRole(
        key="act",
        name="Act",
        description="Full execution and implementation role",
        read_only=False,
        prompt=(
            "## Execution Mode: ACT\n\n"
            "### Overview\n"
            "Execution and implementation mode. Write, edit, shell, and task tools are fully enabled.\n\n"
            "### Action Rules\n"
            "1. Precision Edits: Use `edit` for single edits and `multi_edit` for multiple non-adjacent edits.\n"
            "2. Verification: Run tests or linters after editing to verify code changes.\n"
            "3. Minimal Complexity (YAGNI): Don't add features/refactorings beyond what was asked. Three similar lines of code is better than a premature abstraction.\n"
            "4. No Unsolicited Commits: Never execute git commits unless explicitly asked."
        ),
        scope="any",
        source="builtin",
    ),
    "worker": AgentRole(
        key="worker",
        name="worker",
        description="General multi-step execution subagent",
        read_only=False,
        prompt=DEFAULT_SUBAGENT_ROLES["worker"]["system_prompt"],
        scope="subagent_only",
        source="builtin",
    ),
    "explore": AgentRole(
        key="explore",
        name="Explore",
        description="Read-only Q&A, codebase research, and planning role",
        read_only=True,
        prompt=(
            "## Execution Mode: EXPLORE\n\n"
            "### Overview\n"
            "Read-only mode for Q&A, codebase research, code explanation, architecture review, and implementation planning.\n\n"
            "### Critical Constraints\n"
            "1. Code modification tools (`create`, `edit`, `multi_edit`) are DISABLED.\n"
            "2. You are STRICTLY PROHIBITED from running state-changing shell commands (mkdir, touch, rm, cp, mv, git add, git commit, redirection operators '>', '>>').\n"
            "3. Use shell ONLY for read-only inspection (ls/find/dir, grep/rg/select-string, git status, git log, git diff, cat/type).\n"
            "4. NEVER call the `ask_user` tool to ask the user if they want to switch out of read-only mode or start implementation. Output your plan/response as normal markdown text in chat, and instruct the user to exit read-only mode (via Shift+Tab) when ready.\n"
            "5. If the user asks to modify code, apply changes, or proceed with implementation while in read-only mode, NEVER claim you are applying changes. Immediately inform the user you are in read-only mode and tell them how to exit it (via Shift+Tab).\n\n"
            "### Response Guidelines\n"
            "1. Q&A / Explanation: Answer questions directly, clearly, and concisely without forcing an implementation plan.\n"
            "2. Planning Request: Outline Goal, Architectural Trade-offs, Critical Files (3-5 key files), and Execution Steps, then suggest exiting read-only mode (via Shift+Tab) when ready to implement.\n"
            "3. Edit / Implementation Request: State clearly that you are in read-only mode and tell the user how to exit it (via Shift+Tab)."
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
    "explorer": AgentRole(
        key="explorer",
        name="explorer",
        description="Fast code exploration subagent",
        read_only=True,
        prompt=DEFAULT_SUBAGENT_ROLES["explorer"]["system_prompt"],
        disallowed_tools=[
            "create",
            "edit",
            "multi_edit",
            "write_to_file",
            "replace_file_content",
            "multi_replace_file_content",
        ],
        scope="subagent_only",
        source="builtin",
    ),
    "orchestrate": AgentRole(
        key="orchestrate",
        name="Orchestrate",
        description="Orchestrator role: plan and delegate bounded subtasks",
        read_only=False,
        prompt=(
            "## Execution Mode: ORCHESTRATE\n\n"
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
            "For isolated execution, delegate to `subagent_type` 'worker'. Prefer "
            "`workspace='branch'` for work that mutates state, then merge the branch.\n\n"
            "### Orchestration Rules\n"
            "1. Decompose first, then delegate: lay out the subtasks and dependencies "
            "before launching anything.\n"
            "2. Load the harness context BEFORE delegating. First (yourself or via an "
            "'explorer' subagent) discover the framework patterns, idioms, and quirks that "
            "subtasks will depend on. Hand subtasks ready-made idioms instead of making them "
            "re-learn the harness. This is the single biggest token saver.\n"
            f"3. Respect the concurrency cap (max {MAX_CONCURRENT_SUBAGENTS} concurrent subagents). Launch only as "
            "many subagents in parallel as is useful; do not saturate the queue blindly.\n"
            "4. Never spawn a subagent for work the main agent can finish faster directly. "
            "If subtasks share significant context, prefer doing them serially yourself over "
            "duplicating that context across N subagents.\n"
            "5. Do not chain subagents recursively or delegate delegation — subagents "
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
            "4. Keep direct edits precise: use `edit` for single edits and `multi_edit` for "
            "multiple non-adjacent edits. Never commit unless explicitly asked."
        ),
        scope="main_only",
        source="builtin",
    ),
}


class RoleRegistry:
    """Unified registry managing agent execution roles."""

    _instance: Optional["RoleRegistry"] = None

    _CACHE_TTL = 2.0  # seconds

    def __init__(self):
        self.roles: Dict[str, AgentRole] = dict(BUILTIN_ROLES)
        self.current_project_dir: Optional[str] = None
        self._roles_cache_signature: Optional[Tuple] = None
        self._roles_cache_ts: float = 0.0

    @classmethod
    def get_instance(cls) -> "RoleRegistry":
        if cls._instance is None:
            cls._instance = RoleRegistry()
        return cls._instance

    def load_roles(self, project_dir: Optional[str] = None, include_global: bool = True) -> Dict[str, AgentRole]:
        if project_dir is not None:
            self.current_project_dir = project_dir
        p_dir = self.current_project_dir or os.getcwd()

        dirs = []
        if include_global:
            dirs.append((os.path.join(CONFIG_DIR, "roles"), "global"))

        dirs.append((os.path.join(p_dir, ".johnston", "roles"), "project"))

        signature = self._roles_signature(dirs)
        now = time.time()
        if (
            signature is not None
            and signature == self._roles_cache_signature
            and (now - self._roles_cache_ts) < self._CACHE_TTL
        ):
            return self.roles

        roles: Dict[str, AgentRole] = dict(BUILTIN_ROLES)
        for fpath, source in iter_md_files(dirs):
            role = self._parse_md_role(fpath, source)
            if role:
                roles[role.key] = role

        self.roles = roles
        self._roles_cache_signature = signature
        self._roles_cache_ts = now
        return roles

    @staticmethod
    def _roles_signature(dirs: List[Tuple[str, str]]) -> Optional[Tuple]:
        """Cheap (path, mtime_ns, size) signature of every role file to detect
        external changes without re-reading contents. None when no dirs exist."""
        entries = []
        for dpath, _source in dirs:
            if not os.path.isdir(dpath):
                continue
            try:
                for fname in sorted(os.listdir(dpath)):
                    if not (fname.endswith(".md") or fname.endswith(".markdown")):
                        continue
                    fpath = os.path.join(dpath, fname)
                    if not os.path.isfile(fpath):
                        continue
                    st = os.stat(fpath)
                    entries.append((fpath, st.st_mtime_ns, st.st_size))
            except OSError:
                continue
        return tuple(entries) if entries else None

    def invalidate_cache(self) -> None:
        """Force the next load_roles/get_role/get_system_prompt_snippet to re-scan from disk."""
        self._roles_cache_signature = None
        self._roles_cache_ts = 0.0

    def get_role(self, key: str, project_dir: Optional[str] = None) -> AgentRole:
        self.load_roles(project_dir=project_dir)
        key_lower = (key or "").lower().strip()
        if key_lower in self.roles:
            return self.roles[key_lower]
        return self.roles.get("act") or self.roles.get("worker") or BUILTIN_ROLES["act"]

    def list_roles(self, scope: Optional[str] = None) -> Dict[str, AgentRole]:
        if not scope:
            return self.roles
        clean_scope = scope.lower().strip()
        return {k: v for k, v in self.roles.items() if v.scope in ("any", clean_scope)}

    def reload(self, project_dir: Optional[str] = None) -> None:
        self.load_roles(project_dir=project_dir)

    def list_subagent_roles(self) -> Dict[str, AgentRole]:
        return {k: v for k, v in self.roles.items() if v.scope in ("any", "subagent_only")}

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
            desc = f": {role.description}" if role.description else ""
            line = f"- `{role.key}`{desc}{tools_info}"
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
                allowed_shell_commands=parse_csv_list(meta.get("allowed_shell_commands")),
                workspace_allowlist=parse_csv_list(meta.get("workspace_allowlist")),
                model=model,
                scope=scope,
                source=source,
            )
        except Exception:
            return None
