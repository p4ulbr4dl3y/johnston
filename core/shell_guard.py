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

    # Unwrap prefixes like rtk, env, time, FOO=bar
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if "=" in token and not token.startswith("-"):
            idx += 1
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

    sensitive_path = _contains_sensitive_path(cmd_str)
    if sensitive_path:
        return False, f"Command touches sensitive path: {sensitive_path}"

    destructive = POSIX_DESTRUCTIVE_COMMANDS | WINDOWS_DESTRUCTIVE_COMMANDS
    for part in _command_parts(cmd_str):
        base_bin = _first_token(part)
        if base_bin in destructive:
            return False, f"Execution of potentially unsafe command: '{base_bin}'"

    return True, "Command is safe"
