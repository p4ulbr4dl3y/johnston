import fnmatch
import os
import re
import shlex
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    from core.infrastructure.platform.paths import LOGS_DIR, SECRETS_FILE
except Exception:
    _cfg = os.environ.get("JOHNSTON_CONFIG_DIR") or os.path.expanduser("~/.johnston")
    LOGS_DIR = os.path.join(_cfg, "logs")
    SECRETS_FILE = os.path.join(_cfg, "secrets.json")

READ_ONLY_TOOLS = frozenset({"read", "view_file", "search"})


def get_config_dir() -> str:
    """Returns the Johnston configuration directory path."""
    try:
        from core.infrastructure.platform import paths

        cd = getattr(paths, "CONFIG_DIR", None)
        if cd:
            return str(cd)
    except Exception:
        pass
    return os.environ.get("JOHNSTON_CONFIG_DIR") or os.path.expanduser("~/.johnston")


def get_trusted_read_roots() -> List[str]:
    """Returns trusted read-only roots (e.g. LOGS_DIR)."""
    roots: List[str] = []
    try:
        from core.infrastructure.platform import paths

        ld = getattr(paths, "LOGS_DIR", None)
        if ld and str(ld) not in roots:
            roots.append(str(ld))
    except Exception:
        pass
    if LOGS_DIR and str(LOGS_DIR) not in roots:
        roots.append(str(LOGS_DIR))
    default_home = os.path.expanduser("~/.johnston/logs")
    if default_home not in roots:
        roots.append(default_home)
    return roots


def get_secrets_files() -> List[str]:
    """Returns all candidate paths for the centralized secrets file."""
    candidates: List[str] = []
    try:
        from core.infrastructure.platform import paths

        sec = getattr(paths, "SECRETS_FILE", None)
        if sec and str(sec) not in candidates:
            candidates.append(str(sec))
    except Exception:
        pass
    if SECRETS_FILE and str(SECRETS_FILE) not in candidates:
        candidates.append(str(SECRETS_FILE))
    default_sec = os.path.expanduser("~/.johnston/secrets.json")
    if default_sec not in candidates:
        candidates.append(default_sec)
    return candidates


def get_secrets_file() -> str:
    """Returns path to the centralized secrets file."""
    files = get_secrets_files()
    return files[0] if files else SECRETS_FILE


def is_secrets_file(
    target_path: str,
    secrets_file: Optional[str] = None,
) -> bool:
    """Checks whether target_path matches or resolves to the centralized SECRETS_FILE."""
    if not target_path or not isinstance(target_path, str) or not target_path.strip():
        return False

    sec_candidates = [secrets_file] if secrets_file else get_secrets_files()
    clean_target = target_path.strip()

    try:
        expanded_target = os.path.expanduser(clean_target)
        norm_target_real = os.path.normcase(os.path.realpath(os.path.abspath(expanded_target))).lower()
        norm_target_abs = os.path.normcase(os.path.abspath(expanded_target)).lower()
    except Exception:
        return False

    target_lower = clean_target.lower().replace("\\", "/")
    if (
        target_lower.endswith("/.johnston/secrets.json")
        or target_lower == ".johnston/secrets.json"
        or target_lower == "~/.johnston/secrets.json"
        or target_lower.endswith("/.config/johnston/secrets.json")
        or target_lower == ".config/johnston/secrets.json"
        or target_lower == "~/.config/johnston/secrets.json"
    ):
        return True

    for sec in sec_candidates:
        if not sec:
            continue
        try:
            norm_sec_real = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(sec.strip())))).lower()
            norm_sec_abs = os.path.normcase(os.path.abspath(os.path.expanduser(sec.strip()))).lower()
        except Exception:
            norm_sec_real = norm_sec_abs = os.path.normcase(os.path.expanduser(sec.strip())).lower()

        if norm_target_real in (norm_sec_real, norm_sec_abs) or norm_target_abs in (norm_sec_real, norm_sec_abs):
            return True

        if target_lower == "secrets.json":
            try:
                cwd_real = os.path.normcase(os.path.realpath(os.getcwd())).lower()
                sec_dir = os.path.normcase(os.path.dirname(norm_sec_real)).lower()
                if cwd_real == sec_dir:
                    return True
            except Exception:
                pass

        if os.path.exists(norm_sec_real) and os.path.exists(norm_target_real):
            try:
                if os.path.samefile(norm_sec_real, norm_target_real):
                    return True
            except (OSError, ValueError, Exception):
                pass

    return False


def is_secrets_shell_command(
    command: str,
    cwd: Optional[str] = None,
    secrets_file: Optional[str] = None,
) -> bool:
    """Detects whether a shell command attempts to read, modify or reference SECRETS_FILE."""
    if not command or not isinstance(command, str) or not command.strip():
        return False

    cmd_lower = command.lower().replace("\\", "/")

    # Check for direct secrets pattern references and globs
    if re.search(r"(\.config/johnston|\.johnston).*secret", cmd_lower):
        return True
    if re.search(r"(\.config/johnston|\.johnston)/[^\s/]*(?:sec\*|\*\.json)", cmd_lower):
        return True

    sec_candidates = [secrets_file] if secrets_file else get_secrets_files()
    norm_cmd = cmd_lower

    if (
        ".johnston/secrets.json" in cmd_lower
        or "~/.johnston/secrets.json" in cmd_lower
        or "$home/.johnston/secrets.json" in cmd_lower
        or "${home}/.johnston/secrets.json" in cmd_lower
        or ".config/johnston/secrets.json" in cmd_lower
        or "~/.config/johnston/secrets.json" in cmd_lower
        or "$home/.config/johnston/secrets.json" in cmd_lower
        or "${home}/.config/johnston/secrets.json" in cmd_lower
    ):
        return True

    eff_cwd = cwd.strip() if cwd and isinstance(cwd, str) and cwd.strip() else ""

    sec_dirs: List[str] = []
    for sec in sec_candidates:
        if not sec:
            continue
        try:
            norm_sec_real = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(sec.strip())))).lower()
            norm_sec_abs = os.path.normcase(os.path.abspath(os.path.expanduser(sec.strip()))).lower()
        except Exception:
            norm_sec_real = norm_sec_abs = os.path.normcase(os.path.expanduser(sec.strip())).lower()

        if norm_sec_real in norm_cmd or norm_sec_abs in norm_cmd:
            return True

        sec_dir = os.path.dirname(norm_sec_real)
        if sec_dir and sec_dir not in sec_dirs:
            sec_dirs.append(sec_dir)

    def _is_johnston_dir(path_str: str) -> bool:
        if not path_str or not isinstance(path_str, str):
            return False
        p = path_str.strip().lower().replace("\\", "/").rstrip("/")
        if (
            p.endswith("/.johnston")
            or p in (".johnston", "~/.johnston", "$home/.johnston", "${home}/.johnston")
            or p.endswith("/.config/johnston")
            or p in (".config/johnston", "~/.config/johnston", "$home/.config/johnston", "${home}/.config/johnston")
            or bool(re.search(r"(\.config/johnston|\.johnston)$", p))
        ):
            return True
        try:
            resolved = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path_str.strip())))).lower()
            if resolved in sec_dirs:
                return True
            if resolved.endswith("/.johnston") or resolved.endswith("/.config/johnston"):
                return True
        except Exception:
            pass
        return False

    current_dir = eff_cwd
    in_secrets_dir = _is_johnston_dir(eff_cwd) if eff_cwd else False

    subcmds = extract_shell_subcommands(command) or [command]
    for sub in subcmds:
        sub_stripped = sub.strip()
        if not sub_stripped:
            continue
        sub_lower = sub_stripped.lower().replace("\\", "/")

        try:
            tokens = shlex.split(sub_stripped)
        except Exception:
            tokens = sub_stripped.split()

        if not tokens:
            continue

        first_tok = tokens[0].lower()
        tok_idx = 0
        if first_tok in ("builtin", "command") and len(tokens) > 1:
            tok_idx = 1
            first_tok = tokens[1].lower()

        if first_tok == "cd":
            cd_args = [t for t in tokens[tok_idx + 1:] if not t.startswith("-") or t == "--"]
            if cd_args and cd_args[0] == "--":
                cd_args = cd_args[1:]
            cd_target = cd_args[0] if cd_args else "~"
            cd_target_cleaned = cd_target.strip("'\"")

            candidate_target = cd_target_cleaned
            if current_dir and not os.path.isabs(os.path.expanduser(candidate_target)):
                candidate_target = os.path.join(current_dir, candidate_target)

            if _is_johnston_dir(cd_target_cleaned) or _is_johnston_dir(candidate_target):
                in_secrets_dir = True
                current_dir = candidate_target
            else:
                in_secrets_dir = False
                current_dir = candidate_target
            continue

        if in_secrets_dir:
            if (
                re.search(r"\bsecret", sub_lower)
                or re.search(r"\bsec\*", sub_lower)
            ):
                return True
            for tok in tokens:
                cleaned = tok.lstrip("<>|&;\"'").rstrip("<>|&;\"'").lower()
                if not cleaned:
                    continue
                if (
                    fnmatch.fnmatch(cleaned, "secret*")
                    or fnmatch.fnmatch(cleaned, "sec*")
                    or fnmatch.fnmatch(cleaned, "*.json")
                    or fnmatch.fnmatch("secrets.json", cleaned)
                ):
                    return True

        for tok in tokens:
            cleaned = tok.lstrip("<>|&;\"'").rstrip("<>|&;\"'")
            if not cleaned:
                continue
            if is_secrets_file(cleaned, secrets_file=secrets_file):
                return True
            if current_dir:
                try:
                    candidate = os.path.join(current_dir, cleaned)
                    if is_secrets_file(candidate, secrets_file=secrets_file):
                        return True
                except Exception:
                    pass

    return False



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
        "view_file",
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
    if canonical in ("create", "edit", "read", "view_file", "search"):
        for key in ("path", "AbsolutePath", "file_path", "target_file", "TargetFile"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None
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
    if canonical in ("create", "edit", "read", "view_file", "search"):
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
    for sub in subcmds:
        sig = extract_command_signature(sub)
        deny_hit = next(
            (
                pair
                for pair in rule_pairs
                if pair[1] == PermissionAction.DENY
                and (match_pattern(sub, pair[0]) or match_pattern(sig, pair[0]))
            ),
            None,
        )
        if deny_hit is not None:
            return PermissionDecision(
                PermissionAction.DENY,
                f"Subcommand '{sub}' matched deny pattern '{deny_hit[0]}'",
            )

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

    if canonical in ("create", "edit", "read", "view_file", "search"):
        return _evaluate_target_rules(target, rules, match_path_pattern, subject=f"Path '{target}'")

    if canonical == "web_fetch":
        return _evaluate_target_rules(target, rules, match_pattern, subject=f"URL '{target}'")

    return None


def is_path_within_workspace(
    target_path: str,
    workspace_roots: Sequence[str],
    allow_temp: bool = True,
    allowed_read_roots: Optional[Sequence[str]] = None,
) -> bool:
    """Checks whether a target path is contained within any of the workspace roots, system temp, or allowed read roots.

    Normalizes paths using realpath and abspath to protect against path traversal and symlink escapes.
    Safely handles missing or invalid paths and exceptions.
    """
    if not target_path or not isinstance(target_path, str) or not target_path.strip():
        return False

    try:
        norm_target = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(target_path.strip()))))
    except Exception:
        return False

    candidates: List[str] = []
    if workspace_roots:
        for r in workspace_roots:
            if isinstance(r, str) and r.strip():
                candidates.append(r.strip())

    for root in candidates:
        try:
            norm_root = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(root))))
            if os.path.commonpath([norm_target, norm_root]) == norm_root:
                return True
        except (ValueError, Exception):
            continue

    if allow_temp:
        # CONFIG_DIR (~/.johnston) is the application directory containing configuration,
        # history, and secrets. It must never be treated as a temporary scratch directory,
        # even if running in test environments where CONFIG_DIR is placed in a temp folder.
        is_in_config_dir = False
        try:
            cfg_dir = get_config_dir()
            if cfg_dir:
                norm_cfg = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(cfg_dir))))
                if os.path.commonpath([norm_target, norm_cfg]) == norm_cfg:
                    is_in_config_dir = True
        except Exception:
            pass

        if not is_in_config_dir:
            temp_candidates = [tempfile.gettempdir(), "/tmp", "/private/tmp"]
            for temp_dir in temp_candidates:
                if not temp_dir:
                    continue
                try:
                    norm_temp = os.path.normcase(os.path.realpath(os.path.abspath(temp_dir)))
                    if os.path.commonpath([norm_target, norm_temp]) == norm_temp:
                        return True
                except (ValueError, Exception):
                    continue

    if allowed_read_roots:
        for r_root in allowed_read_roots:
            if not r_root or not isinstance(r_root, str) or not r_root.strip():
                continue
            try:
                norm_r = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(r_root.strip()))))
                if os.path.commonpath([norm_target, norm_r]) == norm_r:
                    return True
            except (ValueError, Exception):
                continue

    return False


def evaluate_workspace_boundary(
    tool_name: str,
    args: Optional[Dict[str, Any]],
    workspace_roots: Sequence[str],
    outside_action: PermissionAction = PermissionAction.ASK,
    allowed_read_roots: Optional[Sequence[str]] = None,
    secrets_file: Optional[str] = None,
) -> Optional[PermissionDecision]:
    """Evaluates whether a tool call accesses a path outside the permitted workspace roots,
    or attempts to access the protected secrets file.

    Extracts path for file tools (create, edit, read, view_file, search) or cwd/command for shell.
    Returns PermissionDecision if path is outside workspace roots or targets secrets, otherwise None.
    """
    canonical = (tool_name or "").strip().lower()

    if canonical == "shell":
        cmd = args.get("command") if isinstance(args, dict) else None
        cwd = args.get("cwd") if isinstance(args, dict) else None
        if cmd and is_secrets_shell_command(cmd, cwd=cwd, secrets_file=secrets_file):
            return PermissionDecision(
                PermissionAction.DENY,
                "Access to secrets file is denied",
            )
        if cwd and isinstance(cwd, str) and cwd.strip():
            if is_secrets_file(cwd.strip(), secrets_file=secrets_file):
                return PermissionDecision(
                    PermissionAction.DENY,
                    f"Access to secrets file '{cwd.strip()}' is denied",
                )
            if not is_path_within_workspace(cwd.strip(), workspace_roots):
                action = outside_action
                if isinstance(action, str):
                    try:
                        action = PermissionAction(action.lower())
                    except ValueError:
                        action = PermissionAction.ASK
                return PermissionDecision(action, f"Path '{cwd.strip()}' is outside workspace roots")
        return None

    target: Optional[str] = None
    if canonical in ("create", "edit", "read", "view_file", "search"):
        target = extract_tool_target_value(canonical, args)

    if not target or not isinstance(target, str) or not target.strip():
        return None

    target = target.strip()

    # 1. Protection for SECRETS_FILE: always DENY across all file tools
    if is_secrets_file(target, secrets_file=secrets_file):
        return PermissionDecision(
            PermissionAction.DENY,
            f"Access to secrets file '{target}' is denied",
        )

    # 2. Workspace boundary check with read-only root support (LOGS_DIR)
    effective_read_roots = None
    if canonical in READ_ONLY_TOOLS:
        effective_read_roots = allowed_read_roots if allowed_read_roots is not None else get_trusted_read_roots()

    if not is_path_within_workspace(target, workspace_roots, allowed_read_roots=effective_read_roots):
        action = outside_action
        if isinstance(action, str):
            try:
                action = PermissionAction(action.lower())
            except ValueError:
                action = PermissionAction.ASK
        return PermissionDecision(action, f"Path '{target}' is outside workspace roots")

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
                tool_key = t.lower()
                existing_rules = base["patterns"].get(tool_key, [])
                if not isinstance(existing_rules, list):
                    existing_rules = []

                rule_by_pattern: Dict[str, str] = {}
                for r in existing_rules:
                    if isinstance(r, dict) and "pattern" in r:
                        pat_key = str(r["pattern"]).strip()
                        if pat_key:
                            rule_by_pattern[pat_key] = normalize_action(str(r.get("action", "ask")))

                for r in norm_rules:
                    pat_key = r["pattern"]
                    act_val = r["action"]
                    # If base already has a DENY rule for this pattern, do not downgrade it
                    if rule_by_pattern.get(pat_key) == "deny" and act_val != "deny":
                        continue
                    rule_by_pattern[pat_key] = act_val

                base["patterns"][tool_key] = [
                    {"pattern": pat, "action": act}
                    for pat, act in rule_by_pattern.items()
                ]
    if "writable_roots" in override and isinstance(override["writable_roots"], list):
        if "writable_roots" not in base or not isinstance(base["writable_roots"], list):
            base["writable_roots"] = []
        for r in override["writable_roots"]:
            if isinstance(r, str) and r.strip() and r.strip() not in base["writable_roots"]:
                base["writable_roots"].append(r.strip())
    if "outside_workspace_action" in override:
        action_val = override["outside_workspace_action"]
        if isinstance(action_val, PermissionAction):
            action_val = action_val.value
        if isinstance(action_val, str):
            cleaned_action = action_val.strip().lower()
            if cleaned_action in ("ask", "deny"):
                base["outside_workspace_action"] = cleaned_action


