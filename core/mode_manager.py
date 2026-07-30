import json
import os
from typing import Dict, List, Optional

from core.config import CONFIG_DIR


class ModeDefinition:
    def __init__(
        self,
        key: str,
        name: str,
        description: str = "",
        read_only: bool = False,
        prompt: str = "",
        disallowed_tools: Optional[List[str]] = None,
        allowed_capabilities: Optional[List[str]] = None,
        denied_capabilities: Optional[List[str]] = None,
        allowed_shell_commands: Optional[List[str]] = None,
        workspace_allowlist: Optional[List[str]] = None,
        source: str = "builtin",
    ):
        self.key = key.lower().strip()
        self.name = name
        self.description = description
        self.read_only = read_only
        self.prompt = prompt
        self.disallowed_tools = [t.strip() for t in (disallowed_tools or [])]
        self.allowed_capabilities = [c.strip() for c in (allowed_capabilities or [])]
        self.denied_capabilities = [c.strip() for c in (denied_capabilities or [])]
        self.allowed_shell_commands = [c.strip() for c in (allowed_shell_commands or [])]
        self.workspace_allowlist = [p.strip() for p in (workspace_allowlist or [])]
        self.source = source


BUILTIN_MODES = {
    "action": ModeDefinition(
        key="action",
        name="Action",
        description="Execution and implementation mode. Full editing, shell, and task permissions.",
        read_only=False,
        allowed_capabilities=[
            "agent.delegate",
            "fs.read",
            "fs.write",
            "mcp.call",
            "network.fetch",
            "shell.exec",
            "skill.read",
            "task.manage",
            "user.prompt",
        ],
        prompt=(
            "## Execution Mode: ACTION\n\n"
            "### Overview\n"
            "Execution and implementation mode. Write, edit, shell, and task tools are fully enabled.\n\n"
            "### Action Rules\n"
            "1. Precision Edits: Use replace_file_content for single edits and multi_replace_file_content for multiple non-adjacent edits.\n"
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
        description="Read-only mode for Q&A, research, code explanation, architecture review, and planning.",
        read_only=True,
        allowed_capabilities=[
            "agent.delegate",
            "fs.read",
            "network.fetch",
            "shell.exec",
            "skill.read",
            "task.manage",
            "user.prompt",
        ],
        denied_capabilities=["fs.write", "mcp.call"],
        prompt=(
            "## Execution Mode: EXPLORE\n\n"
            "### Overview\n"
            "Read-only mode for Q&A, codebase research, code explanation, architecture review, and implementation planning.\n\n"
            "### Critical Constraints\n"
            "1. Code modification tools (create, edit) are DISABLED.\n"
            "2. You are STRICTLY PROHIBITED from running state-changing shell commands (mkdir, touch, rm, cp, mv, git add, git commit, redirection operators '>', '>>').\n"
            "3. Use shell ONLY for read-only inspection (ls/find/dir, grep/rg/select-string, git status, git log, git diff, cat/type).\n"
            "4. NEVER call the ask_user tool to ask the user if they want to switch to Action mode or start implementation. Output your plan/response as normal markdown text in chat, and instruct the user to press Shift+Tab or type /action when ready.\n"
            "5. If the user asks to modify code, apply changes, or proceed with implementation while in Explore mode, NEVER claim you are applying changes. Immediately inform the user you are in read-only Explore mode and tell them to press Shift+Tab or type /action to switch to Action mode.\n\n"
            "### Response Guidelines\n"
            "1. Q&A / Explanation: Answer questions directly, clearly, and concisely without forcing an implementation plan.\n"
            "2. Planning Request: Outline Goal, Architectural Trade-offs, Critical Files (3-5 key files), and Execution Steps, then suggest switching to Action mode (via Shift+Tab or /action) when ready to implement.\n"
            "3. Edit / Implementation Request: State clearly that you are in Explore mode and tell the user to press Shift+Tab or type /action to switch to Action mode."
        ),
        disallowed_tools=[
            "create", "edit", "Create", "Edit",
            "replace_file_content", "multi_replace_file_content",
            "replace", "multi_replace", "write_file", "save_file"
        ],
        source="builtin",
    ),
}


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

        for dpath, source in dirs:
            if not os.path.isdir(dpath):
                continue
            for fname in sorted(os.listdir(dpath)):
                fpath = os.path.join(dpath, fname)
                if not os.path.isfile(fpath):
                    continue
                mode_def = None
                if fname.endswith(".json"):
                    mode_def = self._parse_json_mode(fpath, source)
                elif fname.endswith(".md") or fname.endswith(".markdown"):
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

    def _parse_json_mode(self, fpath: str, source: str) -> Optional[ModeDefinition]:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = data.get("key") or os.path.splitext(os.path.basename(fpath))[0]
            name = data.get("name") or key.capitalize()
            return ModeDefinition(
                key=key,
                name=name,
                description=data.get("description", ""),
                read_only=bool(data.get("read_only", False)),
                prompt=data.get("prompt", ""),
                disallowed_tools=data.get("disallowed_tools", []),
                allowed_capabilities=data.get("allowed_capabilities", []),
                denied_capabilities=data.get("denied_capabilities", []),
                allowed_shell_commands=data.get("allowed_shell_commands", []),
                workspace_allowlist=data.get("workspace_allowlist", []),
                source=source,
            )
        except Exception:
            return None

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
                description=meta.get("description", ""),
                read_only=read_only_val,
                prompt=prompt,
                disallowed_tools=disallowed_tools,
                allowed_capabilities=_parse_list("allowed_capabilities"),
                denied_capabilities=_parse_list("denied_capabilities"),
                allowed_shell_commands=_parse_list("allowed_shell_commands"),
                workspace_allowlist=_parse_list("workspace_allowlist"),
                source=source,
            )
        except Exception:
            return None
