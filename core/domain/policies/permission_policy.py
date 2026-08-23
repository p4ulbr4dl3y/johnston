import fnmatch
import os
import re
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class PermissionAction(str, Enum):
    """Outcome of a tool permission check."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


VALID_ACTIONS = frozenset(action.value for action in PermissionAction)


@dataclass(frozen=True)
class PermissionDecision:
    """Result of a tool permission check: the action and a human-readable reason."""

    action: PermissionAction
    reason: str


# Builtin tools that are NOT covered by an explicit config entry fall back to
# the configured default action (ask/deny). MCP tools (not in this set) default
# to 'allow'. Used as the fallback when no builtin_tool_names frozenset is
# injected via DI.
_BUILTIN_TOOLS = frozenset(
    {
        "read",
        "create",
        "edit",
        "multi_edit",
        "shell",
        "ask_user",
        "web_fetch",
        "invoke_subagent",
        "manage_subagent",
        "manage_shell",
        "update_plan",
    }
)

_MULTI_COMMAND_TOOLS = frozenset(
    {
        "git",
        "docker",
        "docker-compose",
        "npm",
        "yarn",
        "pnpm",
        "uv",
        "cargo",
        "pip",
        "python",
        "pytest",
        "kubectl",
        "systemctl",
        "service",
        "go",
        "make",
    }
)

_WRAPPER_COMMANDS = frozenset(
    {
        "sudo",
        "env",
        "nohup",
        "time",
        "nice",
        "xargs",
        "builtin",
        "command",
    }
)

_UNSAFE_SHELL_REGEX = re.compile(
    r"(\$\(|`|\b(?:bash|sh|zsh|dash|powershell|pwsh)\s+-c\b|\beval\s+|\bexec\s+)",
    re.IGNORECASE,
)


def normalize_action(action: str, default: str = "ask") -> str:
    """Normalizes an action to 'allow'/'ask'/'deny'. Invalid values fall back to default."""
    if isinstance(action, str):
        cleaned = action.strip().lower()
        if cleaned in VALID_ACTIONS:
            return cleaned
    return default


def extract_shell_subcommands(cmd: str) -> List[str]:
    """Splits compound shell commands (&&, ||, ;, |, &) into individual subcommands."""
    if not cmd or not isinstance(cmd, str):
        return []
    # Split by chain and pipeline delimiters, ignoring redirection operators like 2>&1
    parts = re.split(r"&&|\|\||;|\||\n|(?<![0-9>&])&(?!>)", cmd)
    cleaned = []
    for part in parts:
        stripped = part.strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned


def has_unsafe_shell_syntax(cmd: str) -> bool:
    """Detects unsafe/dynamic shell syntax that cannot be safely validated by static patterns."""
    if not cmd or not isinstance(cmd, str):
        return False
    return bool(_UNSAFE_SHELL_REGEX.search(cmd))


def extract_command_signature(cmd: str) -> str:
    """Extracts a normalized command signature (e.g. 'git status *' or 'cat *')."""
    if not cmd or not isinstance(cmd, str):
        return ""
    try:
        tokens = shlex.split(cmd)
    except Exception:
        tokens = cmd.strip().split()

    # Skip variable assignments and wrappers (e.g. FOO=1 sudo git ...)
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if "=" in token and not token.startswith("-"):
            idx += 1
            continue
        if token in _WRAPPER_COMMANDS:
            idx += 1
            continue
        break

    meaningful = tokens[idx:]
    if not meaningful:
        return cmd.strip()

    binary = os.path.basename(meaningful[0])
    if binary in _MULTI_COMMAND_TOOLS and len(meaningful) > 1 and not meaningful[1].startswith("-"):
        return f"{binary} {meaningful[1]} *"
    return f"{binary} *"


def match_pattern(value: str, pattern: str) -> bool:
    """Matches a string value against a wildcard pattern."""
    if not pattern:
        return False
    val = value.strip()
    pat = pattern.strip()
    return fnmatch.fnmatch(val, pat) or fnmatch.fnmatchcase(val, pat)


def match_path_pattern(path: str, pattern: str) -> bool:
    """Matches a file path against a pattern, normalizing path traversal and separators."""
    if not path or not pattern:
        return False
    pat = pattern.strip().replace("\\", "/")
    norm_p = os.path.normpath(path.strip()).replace("\\", "/")
    basename = os.path.basename(norm_p)

    # Match normalized path or basename
    if fnmatch.fnmatch(norm_p, pat) or fnmatch.fnmatch(basename, pat):
        return True

    # Suffix/subpath match (e.g. 'tests/**' matching '/a/b/tests/test_x.py')
    if pat.endswith("/**") or pat.endswith("/*"):
        prefix = pat.rstrip("/*")
        if prefix and (f"/{prefix}/" in norm_p or norm_p.startswith(f"{prefix}/") or norm_p == prefix):
            return True

    return False



def extract_tool_target_value(tool_name: str, args: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extracts the primary target argument (command, path, or url) for a given tool."""
    if not args or not isinstance(args, dict):
        return None
    canonical = (tool_name or "").strip().lower()
    if canonical == "shell":
        return args.get("command") or args.get("cmd")
    if canonical in ("create", "edit", "multi_edit", "read"):
        return args.get("path") or args.get("file_path") or args.get("filepath")
    if canonical == "web_fetch":
        return args.get("url") or args.get("uri")
    return None


def suggest_pattern(tool_name: str, args: Optional[Dict[str, Any]]) -> Optional[str]:
    """Suggests a pattern signature suitable for session pattern allow."""
    val = extract_tool_target_value(tool_name, args)
    if not val:
        return None
    canonical = (tool_name or "").strip().lower()
    if canonical == "shell":
        return extract_command_signature(val)
    if canonical in ("create", "edit", "multi_edit", "read"):
        # Suggest directory pattern or basename
        dirname = os.path.dirname(val)
        if dirname and dirname not in (".", "/"):
            return f"{dirname}/**"
        return val
    if canonical == "web_fetch":
        # Suggest domain pattern
        match = re.match(r"(https?://[^/]+)", val)
        if match:
            return f"{match.group(1)}/*"
        return f"{val}*"
    return None


def evaluate_pattern_rules(
    tool_name: str,
    args: Optional[Dict[str, Any]],
    rules: List[Dict[str, Any]],
) -> Optional[PermissionDecision]:
    """
    Evaluates pattern rules for a tool call.

    Returns PermissionDecision if any matching rule definitively decides the action,
    or None if no rule matches (allowing fallback to tool-level permission).
    """
    if not rules:
        return None

    target = extract_tool_target_value(tool_name, args)
    if target is None:
        return None

    canonical = (tool_name or "").strip().lower()

    if canonical == "shell":
        if has_unsafe_shell_syntax(target):
            return PermissionDecision(
                PermissionAction.ASK,
                f"Shell command contains dynamic/unsafe constructs: '{target}'",
            )
        subcmds = extract_shell_subcommands(target)
        if not subcmds:
            return None

        matched_decisions: List[Tuple[PermissionAction, str, str]] = []
        for sub in subcmds:
            sig = extract_command_signature(sub)
            sub_matched = False
            for r in rules:
                if not isinstance(r, dict):
                    continue
                pat = str(r.get("pattern", "")).strip()
                if not pat:
                    continue
                if match_pattern(sub, pat) or match_pattern(sig, pat):
                    act = PermissionAction(normalize_action(r.get("action", "ask")))
                    matched_decisions.append((act, sub, pat))
                    sub_matched = True
                    break
            if not sub_matched:
                # If any subcommand is not covered by pattern rules, fall back to tool level
                return None

        # Fail-closed priority: DENY > ASK > ALLOW
        for act, sub, pat in matched_decisions:
            if act == PermissionAction.DENY:
                return PermissionDecision(
                    PermissionAction.DENY,
                    f"Subcommand '{sub}' matched deny pattern '{pat}'",
                )
        for act, sub, pat in matched_decisions:
            if act == PermissionAction.ASK:
                return PermissionDecision(
                    PermissionAction.ASK,
                    f"Subcommand '{sub}' matched ask pattern '{pat}'",
                )
        return PermissionDecision(
            PermissionAction.ALLOW,
            f"All subcommands matched allow patterns: '{target}'",
        )

    if canonical in ("create", "edit", "multi_edit", "read"):
        for r in rules:
            if not isinstance(r, dict):
                continue
            pat = str(r.get("pattern", "")).strip()
            if not pat:
                continue
            if match_path_pattern(target, pat):
                act = PermissionAction(normalize_action(r.get("action", "ask")))
                return PermissionDecision(
                    act,
                    f"Path '{target}' matched pattern '{pat}' for '{canonical}'",
                )

    if canonical == "web_fetch":
        for r in rules:
            if not isinstance(r, dict):
                continue
            pat = str(r.get("pattern", "")).strip()
            if not pat:
                continue
            if match_pattern(target, pat):
                act = PermissionAction(normalize_action(r.get("action", "ask")))
                return PermissionDecision(
                    act,
                    f"URL '{target}' matched pattern '{pat}'",
                )

    return None


def _merge_perms(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    if not override:
        return
    if "default" in override and isinstance(override["default"], str):
        base["default"] = normalize_action(override["default"])
    if "tools" in override and isinstance(override["tools"], dict):
        if "tools" not in base or not isinstance(base["tools"], dict):
            base["tools"] = {}
        for t, act in override["tools"].items():
            if isinstance(act, str):
                base["tools"][t.lower()] = normalize_action(act)
    if "patterns" in override and isinstance(override["patterns"], dict):
        if "patterns" not in base or not isinstance(base["patterns"], dict):
            base["patterns"] = {}
        for t, rule_list in override["patterns"].items():
            if isinstance(rule_list, list):
                norm_rules = []
                for r in rule_list:
                    if isinstance(r, dict) and "pattern" in r:
                        pat = str(r["pattern"]).strip()
                        act = normalize_action(str(r.get("action", "ask")))
                        if pat and act in VALID_ACTIONS:
                            norm_rules.append({"pattern": pat, "action": act})
                base["patterns"][t.lower()] = norm_rules

