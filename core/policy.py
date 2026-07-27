import ntpath
import os
import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.policy_config import get_policy_config
from core.shell_guard import analyze_shell_command

READ_ONLY_SHELL_COMMANDS = {
    "cat",
    "cd",
    "dir",
    "echo",
    "find",
    "get-childitem",
    "get-command",
    "get-content",
    "get-item",
    "get-location",
    "git",
    "grep",
    "head",
    "ls",
    "measure-object",
    "more",
    "pwd",
    "rg",
    "sed",
    "select-string",
    "sort-object",
    "tail",
    "type",
    "tree",
    "ver",
    "wc",
    "where",
    "where-object",
}

READ_ONLY_GIT_SUBCOMMANDS = {
    "branch",
    "diff",
    "log",
    "show",
    "status",
}

READ_ONLY_PACKAGE_RUNNERS = {"pytest", "ruff", "mypy", "pyright", "tsc"}

SHELL_WRITE_TOKENS = re.compile(
        r"(^|[\s;&|])("
        r"rm|rmdir|mv|cp|dd|mkfs|truncate|touch|chmod|chown|sudo|su|"
        r"del|erase|copy|xcopy|robocopy|move|ren|rename|md|mkdir|"
        r"remove-item|new-item|set-content|add-content|clear-content|"
        r"copy-item|move-item|rename-item|set-item|"
        r"git\s+(checkout|clean|commit|merge|pull|push|rebase|reset|restore|switch)|"
    r"npm\s+(install|publish|update)|pnpm\s+(install|publish|update)|"
    r"yarn\s+(add|install|publish|upgrade)|uv\s+(add|remove|sync)|"
    r"pip\s+install|python\s+-c|python3\s+-c"
    r")\b",
    re.IGNORECASE,
)

SHELL_REDIRECT_TOKENS = re.compile(r"(^|[^<])>(?!>)|>>|<<")


TOOL_CAPABILITIES: dict[str, set[str]] = {
    "ask_user": {"user.prompt"},
    "call_mcp_tool": {"mcp.call"},
    "create": {"fs.write"},
    "edit": {"fs.write"},
    "manage_subagent": {"agent.delegate"},
    "manage_task": {"task.manage"},
    "read": {"fs.read"},
    "shell": {"shell.exec"},
    "skill": {"skill.read"},
    "subagent": {"agent.delegate"},
    "view_image": {"fs.read"},
    "web_fetch": {"network.fetch"},
}

TOOL_ALIASES: dict[str, str] = {
    "cat": "read",
    "create_file": "create",
    "exec": "shell",
    "modify_file": "edit",
    "read_file": "read",
    "run_command": "shell",
    "save_file": "create",
    "str_replace_editor": "edit",
    "terminal": "shell",
    "update_file": "edit",
    "view_file": "read",
    "write": "create",
    "write_file": "create",
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    capabilities: set[str] = field(default_factory=set)
    action: str = "allow"

    @classmethod
    def allow(cls, capabilities: Iterable[str] = (), reason: str = "Allowed") -> "PolicyDecision":
        return cls(True, reason, set(capabilities), "allow")

    @classmethod
    def block(cls, reason: str, capabilities: Iterable[str] = ()) -> "PolicyDecision":
        return cls(False, reason, set(capabilities), "block")

    @classmethod
    def ask(cls, reason: str, capabilities: Iterable[str] = ()) -> "PolicyDecision":
        return cls(False, reason, set(capabilities), "ask")


def canonical_tool_name(name: str) -> str:
    clean_name = (name or "").strip()
    if clean_name.startswith("functions."):
        clean_name = clean_name.split(".", 1)[1]
    return TOOL_ALIASES.get(clean_name.lower(), clean_name).lower()


def workspace_root() -> str:
    return os.path.realpath(os.getcwd())


def resolve_workspace_path(path_str: str | None, *, root: str | None = None) -> str:
    if not path_str:
        candidate = root or workspace_root()
    else:
        candidate = os.path.abspath(os.path.expanduser(path_str))
    real_root = os.path.realpath(root or workspace_root())
    real_candidate = os.path.realpath(candidate)
    comparable_root = os.path.normcase(real_root)
    comparable_candidate = os.path.normcase(real_candidate)
    if comparable_candidate != comparable_root and not comparable_candidate.startswith(
        comparable_root + os.sep
    ):
        raise PermissionError(f"Path '{candidate}' is outside workspace '{real_root}'.")
    return candidate


def _shell_command_name(raw_command: str) -> str:
    command = ntpath.basename(os.path.basename(raw_command)).lower()
    if command.endswith((".exe", ".cmd", ".bat", ".ps1")):
        command = command.rsplit(".", 1)[0]
    return command


def shell_command_is_read_only(command: str) -> bool:
    command = (command or "").strip()
    if not command:
        return False
    if "$(" in command or "`" in command:
        return False
    if SHELL_REDIRECT_TOKENS.search(command) or SHELL_WRITE_TOKENS.search(command):
        return False

    segments = re.split(r"\s*(?:&&|\|\||;|\|)\s*", command)
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        try:
            parts = shlex.split(
                segment, posix=not bool(re.match(r"^[A-Za-z]:\\", segment))
            )
        except ValueError:
            return False
        if not parts:
            continue
        if _is_read_only_test_command(parts):
            continue
        cmd = _shell_command_name(parts[0])
        if cmd not in READ_ONLY_SHELL_COMMANDS:
            return False
        if cmd == "git":
            if len(parts) < 2 or parts[1] not in READ_ONLY_GIT_SUBCOMMANDS:
                return False
        if cmd == "sed" and "-i" in parts:
            return False
    return True


def _is_read_only_test_command(parts: list[str]) -> bool:
    if not parts:
        return False
    cmd = _shell_command_name(parts[0])
    if cmd in READ_ONLY_PACKAGE_RUNNERS:
        return cmd != "ruff" or "check" in parts
    if cmd == "uv" and len(parts) >= 4 and parts[1] == "run":
        runner = _shell_command_name(parts[2])
        if runner == "python" and len(parts) >= 5 and parts[3] == "-m":
            return parts[4] in {"unittest", "pytest", "mypy"}
        return runner in READ_ONLY_PACKAGE_RUNNERS
    if cmd in {"npm", "pnpm", "yarn"} and len(parts) >= 3 and parts[1] == "run":
        return any(word in parts[2].lower() for word in ("test", "lint", "check", "type"))
    return False


class PolicyEngine:
    def capabilities_for_tool(self, tool_name: str) -> set[str]:
        canonical = canonical_tool_name(tool_name)
        capabilities = set(TOOL_CAPABILITIES.get(canonical, set()))
        if capabilities:
            return capabilities
        try:
            from core.mcp_manager import get_mcp_manager

            return set(get_mcp_manager().get_capabilities_for_exposed_tool(tool_name))
        except Exception:
            return set()

    def tool_allowed_in_prompt(self, tool_name: str, mode_def: Any) -> PolicyDecision:
        canonical = canonical_tool_name(tool_name)
        capabilities = self.capabilities_for_tool(canonical)
        if not capabilities:
            return PolicyDecision.block(f"Tool '{tool_name}' has no declared capabilities.")
        mode_decision = self._mode_decision(canonical, capabilities, mode_def)
        if not mode_decision.allowed:
            return mode_decision
        action = get_policy_config().action_for(
            tool=canonical, capabilities=capabilities, default="allow"
        )
        if action == "block":
            return PolicyDecision.block("Tool is blocked by policy config.", capabilities)
        return mode_decision

    def tool_call_decision(
        self,
        tool_name: str,
        args: dict[str, Any],
        mode_def: Any,
        *,
        approved: bool = False,
    ) -> PolicyDecision:
        canonical = canonical_tool_name(tool_name)
        capabilities = self.capabilities_for_tool(canonical)
        policy_config = get_policy_config()
        if not capabilities:
            return PolicyDecision.block(f"Tool '{tool_name}' has no declared capabilities.")

        mode_decision = self._mode_decision(canonical, capabilities, mode_def)
        if not mode_decision.allowed:
            return mode_decision

        if capabilities & {"fs.read", "fs.write"}:
            path = args.get("path") or args.get("file") or args.get("image_path")
            if path:
                try:
                    resolve_workspace_path(path)
                except PermissionError as exc:
                    return PolicyDecision.block(str(exc), capabilities)

        config_action = policy_config.action_for(
            tool=canonical, capabilities=capabilities, default="allow"
        )
        if config_action == "block":
            return PolicyDecision.block("Tool is blocked by policy config.", capabilities)
        if config_action == "ask" and not approved:
            return PolicyDecision.ask("Tool requires approval by policy config.", capabilities)

        if canonical == "shell":
            command = args.get("command", "")
            if getattr(mode_def, "read_only", False):
                if not shell_command_is_read_only(command):
                    return PolicyDecision.block(
                        "Shell command is not allowed in read-only mode.", capabilities
                    )
            else:
                is_safe, reason = analyze_shell_command(command)
                if not is_safe and not approved:
                    action = policy_config.action_for(tool=canonical, capabilities=capabilities, default="ask")
                    if action == "allow":
                        return PolicyDecision.allow(capabilities)
                    if action == "block":
                        return PolicyDecision.block(reason, capabilities)
                    return PolicyDecision.ask(reason, capabilities)

        if canonical == "call_mcp_tool":
            mcp_caps = self._mcp_capabilities(args)
            if not mcp_caps:
                return PolicyDecision.block(
                    "MCP tool calls require explicit capability metadata.", capabilities
                )
            mcp_mode_decision = self._mode_decision(canonical, mcp_caps, mode_def)
            if not mcp_mode_decision.allowed:
                return mcp_mode_decision
            action = policy_config.action_for(tool=canonical, capabilities=mcp_caps, default="allow")
            if action == "block":
                return PolicyDecision.block("MCP tool is blocked by policy config.", mcp_caps)
            if action == "ask" and not approved:
                return PolicyDecision.ask("MCP tool requires approval by policy config.", mcp_caps)
            if "network.fetch" in mcp_caps and not approved:
                action = policy_config.action_for(tool=canonical, capabilities=mcp_caps, default="ask")
                if action == "block":
                    return PolicyDecision.block("MCP tool can access the network.", mcp_caps)
                if action == "ask":
                    return PolicyDecision.ask("MCP tool can access the network.", mcp_caps)

        return PolicyDecision.allow(capabilities)

    def _mcp_capabilities(self, args: dict[str, Any]) -> set[str]:
        server = str(args.get("server") or "")
        tool = str(args.get("tool") or "")
        if not server or not tool:
            return set()
        try:
            from core.mcp_manager import get_mcp_manager

            return set(get_mcp_manager().get_tool_capabilities(server, tool))
        except Exception:
            return set()

    def _mode_decision(self, tool_name: str, capabilities: set[str], mode_def: Any) -> PolicyDecision:
        denied = set(getattr(mode_def, "denied_capabilities", []) or [])
        allowed = set(getattr(mode_def, "allowed_capabilities", []) or [])

        for disallowed_tool in getattr(mode_def, "disallowed_tools", []) or []:
            if canonical_tool_name(disallowed_tool) == tool_name:
                return PolicyDecision.block(
                    f"Tool '{tool_name}' is disabled in {mode_def.name} mode.", capabilities
                )

        if denied and capabilities & denied:
            return PolicyDecision.block(
                f"Capability denied in {mode_def.name} mode: {', '.join(sorted(capabilities & denied))}.",
                capabilities,
            )
        if allowed and not capabilities <= allowed:
            return PolicyDecision.block(
                f"Capability not allowed in {mode_def.name} mode: {', '.join(sorted(capabilities - allowed))}.",
                capabilities,
            )
        if getattr(mode_def, "read_only", False) and "fs.write" in capabilities:
            return PolicyDecision.block("File writes are disabled in read-only mode.", capabilities)
        return PolicyDecision.allow(capabilities)


policy_engine = PolicyEngine()
