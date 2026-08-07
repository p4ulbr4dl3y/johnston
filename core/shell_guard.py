import ntpath
import os
import re
import shlex
from typing import Tuple

from core.platform_utils import is_windows

POSIX_DESTRUCTIVE_COMMANDS = {
    "rm",
    "rmdir",
    "dd",
    "mkfs",
    "fdisk",
    "truncate",
    "chmod",
    "chown",
    "reboot",
    "shutdown",
}

WINDOWS_DESTRUCTIVE_COMMANDS = {
    "del",
    "erase",
    "format",
    "powershell.remove-item",
    "rd",
    "reg",
    "remove-item",
    "rmdir",
    "set-executionpolicy",
    "shutdown",
    "takeown",
}

IGNORED_COMMAND_PREFIXES = {"rtk", "env", "time", "nohup", "nice", "sudo"}

# Flags that consume a following argument (e.g. 'sudo -u root rm').
FLAG_WITH_ARG = {"-u", "--user", "-g", "--group", "-p", "--password", "-h", "--host", "-l", "--login", "-c", "--command", "-m", "-n", "-t", "-S", "--setenv", "-C", "--chdir", "-w", "--workdir"}

# Indirection patterns that can smuggle destructive commands past token checks.
COMMAND_SUBSTITUTION_RE = re.compile(r"\$\(|\$\(\(|`")
SHELL_WRAPPER_RE = re.compile(r"(?:\bsh\b|\bbash\b|\bzsh\b|\bk\b|\bpython3?\b|\bperl\b|\bnode\b|\bruby\b)\s+-(?:c|e)\b", re.IGNORECASE)
XARGS_RE = re.compile(r"\bxargs\b", re.IGNORECASE)
FIND_DELETE_RE = re.compile(r"\bfind\b.*\s-delete\b", re.IGNORECASE)

DANGEROUS_GIT_REGEX = re.compile(r"\bgit\s+(?:push|reset\s+--hard|clean\s+-[a-zA-Z]*f[a-zA-Z]*)\b", re.IGNORECASE)

POSIX_SENSITIVE_PATHS = ("/etc", "/sys", "/proc", "/root", "~/.ssh")
WINDOWS_SENSITIVE_PATHS = (
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
    r"%appdata%\microsoft",
    r"%userprofile%\.ssh",
)


def _command_parts(command: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?:&&|\|\||;|\|)", command) if part.strip()]


def _first_token(part: str) -> str:
    try:
        tokens = shlex.split(part, posix=not is_windows())
    except Exception:
        tokens = part.split()

    if not tokens:
        return ""

    # Unwrap prefixes like rtk, env, time, FOO=bar and skip flags (and their args)
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if "=" in token and not token.startswith("-"):
            idx += 1
            continue
        if token.startswith("-") and token != "-":
            idx += 2 if token in FLAG_WITH_ARG else 1
            continue
        clean_bin = (ntpath.basename(token) if is_windows() else os.path.basename(token)).lower()
        if clean_bin.endswith((".exe", ".cmd", ".bat", ".ps1")):
            clean_bin = clean_bin.rsplit(".", 1)[0]
        if clean_bin in IGNORED_COMMAND_PREFIXES:
            idx += 1
            continue
        return clean_bin

    return ""


def _contains_sensitive_path(command: str) -> str | None:
    lowered = command.lower()
    for path in POSIX_SENSITIVE_PATHS:
        if path in lowered:
            return path
    for path in WINDOWS_SENSITIVE_PATHS:
        if path in lowered:
            return path
    return None


def analyze_shell_command(command: str) -> Tuple[bool, str]:
    """
    Analyzes a shell command for safety before execution across Windows, macOS, and Linux.

    Returns (is_safe, reason).
    """
    cmd_str = command.strip()
    if not cmd_str:
        return True, "Empty command"

    if DANGEROUS_GIT_REGEX.search(cmd_str):
        return False, "Potentially dangerous Git operation (push, reset --hard, clean -f)"

    if COMMAND_SUBSTITUTION_RE.search(cmd_str):
        return False, "Command substitution detected ($(...) or backticks)"

    if SHELL_WRAPPER_RE.search(cmd_str):
        return False, "Shell/interpreter -c/-e wrapper detected (may hide destructive commands)"

    if XARGS_RE.search(cmd_str):
        return False, "xargs indirection detected (may invoke destructive commands)"

    if FIND_DELETE_RE.search(cmd_str):
        return False, "find -delete detected (bulk file deletion)"

    sensitive_path = _contains_sensitive_path(cmd_str)
    if sensitive_path:
        return False, f"Command touches sensitive path: {sensitive_path}"

    destructive = POSIX_DESTRUCTIVE_COMMANDS | WINDOWS_DESTRUCTIVE_COMMANDS
    for part in _command_parts(cmd_str):
        base_bin = _first_token(part)
        if base_bin in destructive:
            return False, f"Execution of potentially unsafe command: '{base_bin}'"

    return True, "Command is safe"
