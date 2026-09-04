import fnmatch
import os
import re
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class PermissionAction(str, Enum):
    """Outcome of a tool permission check."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


VALID_ACTIONS = frozenset(action.value for action in PermissionAction)


class ExecutionMode(str, Enum):
    """Execution / Approval Mode for tool authorization."""

    REVIEW = "review"
    EDITS = "edits"
    YOLO = "yolo"


VALID_EXECUTION_MODES = frozenset(mode.value for mode in ExecutionMode)

MODE_TOOL_BASELINES: Dict[ExecutionMode, Dict[str, PermissionAction]] = {
    ExecutionMode.REVIEW: {
        "create": PermissionAction.ASK,
        "edit": PermissionAction.ASK,
        "shell": PermissionAction.ASK,
        "web_fetch": PermissionAction.ASK,
        "_mcp": PermissionAction.ASK,
        "default": PermissionAction.ALLOW,
    },
    ExecutionMode.EDITS: {
        "create": PermissionAction.ALLOW,
        "edit": PermissionAction.ALLOW,
        "shell": PermissionAction.ASK,
        "web_fetch": PermissionAction.ALLOW,
        "_mcp": PermissionAction.ALLOW,
        "default": PermissionAction.ALLOW,
    },
    ExecutionMode.YOLO: {
        "create": PermissionAction.ALLOW,
        "edit": PermissionAction.ALLOW,
        "shell": PermissionAction.ALLOW,
        "web_fetch": PermissionAction.ALLOW,
        "_mcp": PermissionAction.ALLOW,
        "default": PermissionAction.ALLOW,
    },
}


def normalize_execution_mode(mode: Any, default: ExecutionMode = ExecutionMode.REVIEW) -> ExecutionMode:
    """Normalizes an execution mode to ExecutionMode enum. Invalid values fallback to default."""
    if isinstance(mode, ExecutionMode):
        return mode
    if isinstance(mode, str):
        cleaned = mode.strip().lower()
        if cleaned == "edits":
            return ExecutionMode.EDITS
        if cleaned == "yolo":
            return ExecutionMode.YOLO
        if cleaned == "review":
            return ExecutionMode.REVIEW
    return default


def get_mode_baseline_action(
    mode: ExecutionMode,
    tool_name: str,
    is_mcp: bool = False,
) -> PermissionAction:
    """Returns the baseline action for a given tool under the specified execution mode."""
    canonical = (tool_name or "").strip().lower()
    table = MODE_TOOL_BASELINES.get(mode, MODE_TOOL_BASELINES[ExecutionMode.REVIEW])
    if is_mcp:
        return table.get("_mcp", table.get("default", PermissionAction.ALLOW))
    if canonical in table:
        return table[canonical]
    return table.get("default", PermissionAction.ALLOW)


@dataclass(frozen=True)
class PermissionDecision:
    """Result of a tool permission check: the action and a human-readable reason."""

    action: PermissionAction
    reason: str


# Builtin tools that are NOT covered by an explicit config entry fall back to
# the configured default action (ask/deny). MCP tools (not in this set) default
# to 'allow'. Used as the fallback when no builtin_tool_names frozenset is
# injected via DI.
BUILTIN_TOOLS = frozenset(
    {
        "read",
        "create",
        "edit",
        "shell",
        "search",
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
    """Splits compound shell commands (&&, ||, ;, |, &) into individual subcommands.

    Quote-aware: delimiters inside single/double quotes (and backslash-escaped
    characters) do not split, so ``git commit -m "fix; rm -rf tmp"`` stays a
    single subcommand instead of producing false ASK/deny fragments.
    """
    if not cmd or not isinstance(cmd, str):
        return []
    parts: List[str] = []
    buf: List[str] = []
    quote: Optional[str] = None
    escaped = False
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if escaped:
            buf.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\":
            buf.append(ch)
            escaped = True
            i += 1
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\n":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        if ch in (";", "|"):
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        if ch == "&":
            nxt = cmd[i + 1] if i + 1 < n else ""
            prev = cmd[i - 1] if i > 0 else ""
            if nxt == "&":  # '&&' chain delimiter
                parts.append("".join(buf))
                buf = []
                i += 2
                continue
            if prev in (">", "&") or nxt == ">":  # keep redirections like 2>&1
                buf.append(ch)
                i += 1
                continue
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
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
    return fnmatch.fnmatch(value.strip(), pattern.strip())


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
        return args.get("command")
    if canonical in ("create", "edit", "read"):
        return args.get("path")
    if canonical == "web_fetch":
        return args.get("url")
    return None


def suggest_pattern(tool_name: str, args: Optional[Dict[str, Any]]) -> Optional[str]:
    """Suggests a pattern signature suitable for session pattern allow."""
    val = extract_tool_target_value(tool_name, args)
    if not val:
        return None
    canonical = (tool_name or "").strip().lower()
    if canonical == "shell":
        return extract_command_signature(val)
    if canonical in ("create", "edit", "read"):
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


def _fail_closed_decision(matched: List[Tuple[PermissionAction, str]]) -> Optional[PermissionDecision]:
    """Picks a decision from collected (action, reason) matches.

    Applies the fail-closed priority DENY > ASK > ALLOW. Returns None when
    nothing matched, allowing callers to fall back to tool-level permission.
    """
    if not matched:
        return None
    for priority in (PermissionAction.DENY, PermissionAction.ASK):
        for act, reason in matched:
            if act == priority:
                return PermissionDecision(act, reason)
    return PermissionDecision(PermissionAction.ALLOW, matched[0][1])


def _iter_rules(rules: List[Dict[str, Any]]) -> List[Tuple[str, PermissionAction]]:
    """Normalizes raw rule dicts into valid (pattern, action) pairs."""
    pairs: List[Tuple[str, PermissionAction]] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        pat = str(r.get("pattern", "")).strip()
        if not pat:
            continue
        pairs.append((pat, PermissionAction(normalize_action(r.get("action", "ask")))))
    return pairs


def _evaluate_shell_rules(cmd: str, rules: List[Dict[str, Any]]) -> Optional[PermissionDecision]:
    if has_unsafe_shell_syntax(cmd):
        return PermissionDecision(
            PermissionAction.ASK,
            f"Shell command contains dynamic/unsafe constructs: '{cmd}'",
        )
    subcmds = extract_shell_subcommands(cmd)
    if not subcmds:
        return None

    rule_pairs = _iter_rules(rules)
    matched: List[Tuple[PermissionAction, str]] = []
    for sub in subcmds:
        sig = extract_command_signature(sub)
        hit = next((pair for pair in rule_pairs if match_pattern(sub, pair[0]) or match_pattern(sig, pair[0])), None)
        if hit is None:
            # If any subcommand is not covered by pattern rules, fall back to tool level
            return None
        pat, act = hit
        matched.append((act, f"Subcommand '{sub}' matched {act.value} pattern '{pat}'"))
    return _fail_closed_decision(matched)


def _evaluate_target_rules(
    target: str,
    rules: List[Dict[str, Any]],
    matcher: Callable[[str, str], bool],
    subject: str,
) -> Optional[PermissionDecision]:
    """Evaluates target-based rules (paths, urls) for a single primary target value."""
    matched = [
        (act, f"{subject} matched {act.value} pattern '{pat}'")
        for pat, act in _iter_rules(rules)
        if matcher(target, pat)
    ]
    return _fail_closed_decision(matched)


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
        return _evaluate_shell_rules(target, rules)

    if canonical in ("create", "edit", "read"):
        return _evaluate_target_rules(target, rules, match_path_pattern, subject=f"Path '{target}'")

    if canonical == "web_fetch":
        return _evaluate_target_rules(target, rules, match_pattern, subject=f"URL '{target}'")

    return None


def merge_perms(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    """Merges a permissions config override into base, in place.

    Tool actions are normalized to 'allow'/'ask'/'deny' (invalid values fail
    closed to 'ask'). The 'default' key is kept raw on purpose: consumers must
    distinguish a configured deny/lock-down from invalid junk that fails closed.
    """
    if not override:
        return
    if "default" in override and isinstance(override["default"], str):
        base["default"] = override["default"]
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
                norm_rules = [
                    {"pattern": pat, "action": act}
                    for pat, act in (
                        (str(r["pattern"]).strip(), normalize_action(str(r.get("action", "ask"))))
                        for r in rule_list
                        if isinstance(r, dict) and "pattern" in r
                    )
                    if pat
                ]
                base["patterns"][t.lower()] = norm_rules

