import os
from typing import Any, Dict, List, Optional

from core.config import CONFIG_DIR, MAX_CONCURRENT_SUBAGENTS


class ModeDefinition:
    def __init__(
        self,
        key: str,
        name: str,
        read_only: bool = False,
        prompt: str = "",
        disallowed_tools: Optional[List[str]] = None,
        allowed_shell_commands: Optional[List[str]] = None,
        workspace_allowlist: Optional[List[str]] = None,
        source: str = "builtin",
    ):
        self.key = key.lower().strip()
        self.name = name
        self.read_only = read_only
        self.prompt = prompt
        self.disallowed_tools = [t.strip() for t in (disallowed_tools or [])]
        self.allowed_shell_commands = [c.strip() for c in (allowed_shell_commands or [])]
        self.workspace_allowlist = [p.strip() for p in (workspace_allowlist or [])]
        self.source = source


BUILTIN_MODES = {
    "action": ModeDefinition(
        key="action",
        name="Action",
        read_only=False,
        prompt=(
            "## Execution Mode: ACTION\n\n"
            "### Overview\n"
            "Execution and implementation mode. Write, edit, shell, and task tools are fully enabled.\n\n"
            "### Action Rules\n"
            "1. Precision Edits: Use edit for single edits and multi_edit for multiple non-adjacent edits.\n"
            "2. Verification: Run tests or linters after editing to verify code changes.\n"
            "3. Minimal Complexity (YAGNI): Don't add features/refactorings beyond what was asked. Three similar lines of code is better than a premature abstraction.\n"
            "4. No Unsolicited Commits: Never execute git commits unless explicitly asked."
        ),
        disallowed_tools=[],
        source="builtin",
    ),
    "explore": ModeDefinition(
        key="explore",
        name="Explore",
        read_only=True,
        prompt=(
            "## Execution Mode: EXPLORE\n\n"
            "### Overview\n"
            "Read-only mode for Q&A, codebase research, code explanation, architecture review, and implementation planning.\n\n"
            "### Critical Constraints\n"
            "1. Code modification tools (create, edit, multi_edit) are DISABLED.\n"
            "2. You are STRICTLY PROHIBITED from running state-changing shell commands (mkdir, touch, rm, cp, mv, git add, git commit, redirection operators '>', '>>').\n"
            "3. Use shell ONLY for read-only inspection (ls/find/dir, grep/rg/select-string, git status, git log, git diff, cat/type).\n"
            "4. NEVER call the ask_user tool to ask the user if they want to switch to Action mode or start implementation. Output your plan/response as normal markdown text in chat, and instruct the user to press Shift+Tab when ready.\n"
            "5. If the user asks to modify code, apply changes, or proceed with implementation while in Explore mode, NEVER claim you are applying changes. Immediately inform the user you are in read-only Explore mode and tell them to press Shift+Tab to switch to Action mode.\n\n"
            "### Response Guidelines\n"
            "1. Q&A / Explanation: Answer questions directly, clearly, and concisely without forcing an implementation plan.\n"
            "2. Planning Request: Outline Goal, Architectural Trade-offs, Critical Files (3-5 key files), and Execution Steps, then suggest switching to Action mode (via Shift+Tab) when ready to implement.\n"
            "3. Edit / Implementation Request: State clearly that you are in Explore mode and tell the user to press Shift+Tab to switch to Action mode."
        ),
        disallowed_tools=[
            "create", "edit", "multi_edit",
            "write_to_file", "replace_file_content", "multi_replace_file_content"
        ],
        source="builtin",
    ),
    "orchestrator": ModeDefinition(
        key="orchestrator",
        name="Orchestrator",
        read_only=False,
        prompt=(
            "## Execution Mode: ORCHESTRATOR\n\n"
            "### Overview\n"
            "You are an orchestrator: you plan, delegate bounded subtasks to subagents, "
            "coordinate them, and integrate their results. You retain full tool access and "
            "decide autonomously when to spawn subagents and when to do the work directly.\n\n"
            "### Decision Rule: Subagents Are A Tool, Not A Default\n"
            "1. Do the work directly when a task is small, tightly coupled, or touches a "
            "single area — spawning a subagent would only add overhead and context cost.\n"
            "2. Delegate to a subagent when a task is clearly bounded and parallelizable: "
            "independent files/modules, independent research, or independent experiments.\n"
            "3. For analysis or reconnaissance, delegate to subagent_type 'explore'. "
            "For isolated execution, delegate to subagent_type 'general'. Prefer "
            "workspace='branch' for work that mutates state, then merge the branch.\n\n"
            "### Orchestration Rules\n"
            "1. Decompose first, then delegate: lay out the subtasks and dependencies "
            "before launching anything.\n"
            f"2. Respect the concurrency cap (max {MAX_CONCURRENT_SUBAGENTS} concurrent subagents). Launch only as "
            "many subagents in parallel as is useful; do not saturate the queue blindly.\n"
            "3. Never spawn a subagent for work the main agent can finish faster directly.\n"
            "4. Do not chain subagents recursively or delegate delegation — subagents "
            "cannot spawn subagents. You are the only orchestrator.\n"
            "5. Use manage_subagent(action='status') sparingly to check on background work; "
            "never poll it in a loop. End your turn and let notifications arrive instead.\n"
            "6. Define reusable project subagents only when a role is genuinely reused across "
            "the task: author .johnston/subagents/<name>.md (frontmatter: name, description, "
            "tools, model; then markdown body as system prompt). They become available as "
            "subagent_type in invoke_subagent. Do not create them for one-off work, do not "
            "duplicate existing definitions, and follow the documented format.\n\n"
            "### Integration Rules\n"
            "1. Collect and synthesize each subagent's <task_result> into a coherent "
            "response; do not dump raw results at the user.\n"
            "2. When subagents return on isolated branches, review the diffs, then ask the "
            "user (via ask_user) before merging (`git merge <branch>`) and before deleting "
            "subagent-created branches (`git branch -D <branch>`).\n"
            "3. Verify integrated work with tests/linters before declaring completion.\n"
            "4. Keep direct edits precise: use edit for single edits and multi_edit for "
            "multiple non-adjacent edits. Never commit unless explicitly asked."
        ),
        disallowed_tools=[],
        source="builtin",
    ),
}


WRITE_TOOLS = {
    "create", "edit", "multi_edit",
    "write", "write_file", "create_file", "save_file", "write_to_file", "touch",
    "edit_file", "replace_file_content", "multi_replace_file_content", "update_file", "modify_file",
}


def mode_tool_error(mode_def: Any, tool_name: str) -> Optional[str]:
    """Returns an error string if mode_def blocks tool_name, else None."""
    if not mode_def:
        return None
    disallowed = [t.lower() for t in (getattr(mode_def, "disallowed_tools", []) or [])]
    clean = (tool_name or "").strip().lower()
    if clean in disallowed:
        return f"ERR: tool '{clean}' disabled in {mode_def.name} mode"
    if getattr(mode_def, "read_only", False) and clean in WRITE_TOOLS:
        return f"ERR: tool '{clean}' disabled in read-only {mode_def.name} mode"
    return None


class ModeManager:
    _instance: Optional["ModeManager"] = None

    def __init__(self):
        self.modes: Dict[str, ModeDefinition] = dict(BUILTIN_MODES)

    @classmethod
    def get_instance(cls) -> "ModeManager":
        if cls._instance is None:
            cls._instance = ModeManager()
        return cls._instance

    def load_modes(self, project_dir: Optional[str] = None, include_global: bool = True) -> Dict[str, ModeDefinition]:
        modes: Dict[str, ModeDefinition] = dict(BUILTIN_MODES)

        dirs = []
        if include_global:
            dirs.append((os.path.join(CONFIG_DIR, "modes"), "global"))
        p_dir = project_dir or os.getcwd()
        dirs.append((os.path.join(p_dir, ".johnston", "modes"), "project"))

        scanned_paths = set()
        for dpath, source in dirs:
            if not os.path.isdir(dpath):
                continue
            rpath = os.path.realpath(dpath)
            if rpath in scanned_paths:
                continue
            scanned_paths.add(rpath)
            for fname in sorted(os.listdir(dpath)):
                fpath = os.path.join(dpath, fname)
                if not os.path.isfile(fpath):
                    continue
                mode_def = None
                if fname.endswith(".md") or fname.endswith(".markdown"):
                    mode_def = self._parse_md_mode(fpath, source)

                if mode_def:
                    modes[mode_def.key] = mode_def

        self.modes = modes
        return modes

    def get_mode(self, key: str, project_dir: Optional[str] = None) -> ModeDefinition:
        self.load_modes(project_dir=project_dir)
        key_lower = key.lower().strip()
        if key_lower in self.modes:
            return self.modes[key_lower]
        # Fallback to action if not found
        return self.modes.get("action", BUILTIN_MODES["action"])

    def _parse_md_mode(self, fpath: str, source: str) -> Optional[ModeDefinition]:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                return None

            base_key = os.path.splitext(os.path.basename(fpath))[0]
            meta = {}
            prompt = raw

            if raw.startswith("---"):
                parts = raw.split("---", 2)
                if len(parts) >= 3:
                    yaml_str = parts[1].strip()
                    prompt = parts[2].strip()
                    for line in yaml_str.splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip().lower()] = v.strip().strip("\"'")

            key = meta.get("key") or base_key
            name = meta.get("name") or key.capitalize()
            read_only_val = str(meta.get("read_only", "false")).lower() in ("true", "1", "yes")

            disallowed_raw = meta.get("disallowed_tools", "")
            disallowed_tools = []
            if disallowed_raw:
                cleaned = disallowed_raw.strip("[]")
                disallowed_tools = [t.strip() for t in cleaned.split(",") if t.strip()]

            def _parse_list(key: str) -> List[str]:
                raw_val = meta.get(key, "")
                if not raw_val:
                    return []
                cleaned_val = raw_val.strip("[]")
                return [v.strip() for v in cleaned_val.split(",") if v.strip()]

            return ModeDefinition(
                key=key,
                name=name,
                read_only=read_only_val,
                prompt=prompt,
                disallowed_tools=disallowed_tools,
                allowed_shell_commands=_parse_list("allowed_shell_commands"),
                workspace_allowlist=_parse_list("workspace_allowlist"),
                source=source,
            )
        except Exception:
            return None
