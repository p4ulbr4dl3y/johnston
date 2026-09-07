"""Shell-command parsing helpers for the permission policy.

Moved verbatim from ``core.domain.policies.permission_policy``.
"""
import os
import re
import shlex
from typing import List, Optional

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
    r"(\$\(|`"
    r"|\b(?:bash|sh|zsh|dash|powershell|pwsh)\s+(?:-[ceE]\b|-command\b|-encodedcommand\b|[^\s-])"
    r"|\b(?:python(?:\d+(?:\.\d+)?)?|node|ruby|perl|php)\b(?:\s+-[^\s\-]+)*\s+(?:-[a-z0-9]*[cer]\b|--eval\b)"
    r"|\|\s*(?:bash|sh|zsh|dash|powershell|pwsh|python(?:\d+(?:\.\d+)?)?|node|ruby|perl|php)\b"
    r"|<\s*(?:bash|sh|zsh|dash)\b"
    r"|\beval\s+|\bexec\s+"
    r"|\bbase64\s+-(?:d|-decode)\b)",
    re.IGNORECASE,
)


def normalize_action(action: str, default: str = "ask") -> str:
    """Normalizes an action to 'allow'/'ask'/'deny'. Invalid values fall back to default."""
    from core.domain.policies.permission_policy import VALID_ACTIONS

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
    if binary in ("python", "python3", "python3.10", "python3.11", "python3.12", "python3.13"):
        if len(meaningful) > 2 and meaningful[1] == "-m":
            return f"{binary} -m {meaningful[2]} *"
        if len(meaningful) > 1 and meaningful[1] in ("-c", "-e"):
            return cmd.strip()
        if len(meaningful) > 1 and not meaningful[1].startswith("-"):
            return f"{binary} {meaningful[1]} *"
        return f"{binary} *"

    if binary in ("node", "ruby", "perl", "php"):
        if len(meaningful) > 1 and meaningful[1] in ("-e", "-c", "-r"):
            return cmd.strip()
        if len(meaningful) > 1 and not meaningful[1].startswith("-"):
            return f"{binary} {meaningful[1]} *"
        return f"{binary} *"

    if binary in _MULTI_COMMAND_TOOLS and len(meaningful) > 1 and not meaningful[1].startswith("-"):
        return f"{binary} {meaningful[1]} *"
    return f"{binary} *"
