import os
import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.bash_guard import analyze_shell_command

READ_ONLY_SHELL_COMMANDS = {
    "cat",
    "find",
    "git",
    "grep",
    "head",
    "ls",
    "pwd",
    "rg",
    "sed",
    "tail",
    "tree",
    "wc",
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
    if real_candidate != real_root and not real_candidate.startswith(real_root + os.sep):
        raise PermissionError(f"Path '{candidate}' is outside workspace '{real_root}'.")
    return candidate


def shell_command_is_read_only(command: str) -> bool:
    command = (command or "").strip()
    if not command:
        return False
    if SHELL_REDIRECT_TOKENS.search(command) or SHELL_WRITE_TOKENS.search(command):
        return False

    segments = re.split(r"\s*(?:&&|\|\||;|\|)\s*", command)
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        try:
            parts = shlex.split(segment)
        except ValueError:
            return False
        if not parts:
            continue
        if _is_read_only_test_command(parts):
            continue
        cmd = os.path.basename(parts[0])
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
    cmd = os.path.basename(parts[0])
    if cmd in READ_ONLY_PACKAGE_RUNNERS:
        return cmd != "ruff" or "check" in parts
    if cmd == "uv" and len(parts) >= 4 and parts[1] == "run":
        runner = os.path.basename(parts[2])
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
        return self._mode_decision(canonical, capabilities, mode_def)

    def tool_call_decision(self, tool_name: str, args: dict[str, Any], mode_def: Any) -> PolicyDecision:
        canonical = canonical_tool_name(tool_name)
        capabilities = self.capabilities_for_tool(canonical)
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

        if canonical == "shell":
            command = args.get("command", "")
            if getattr(mode_def, "read_only", False):
                if not shell_command_is_read_only(command):
                    return PolicyDecision.block(
                        "Shell command is not allowed in read-only mode.", capabilities
                    )
            else:
                is_safe, reason = analyze_shell_command(command)
                if not is_safe and not args.get("policy_approved"):
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
            if "network.fetch" in mcp_caps and not args.get("policy_approved"):
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
