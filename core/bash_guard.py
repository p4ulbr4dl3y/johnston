import ntpath
import os
import re
import shlex
from typing import Tuple

from core.platform_utils import is_windows

POSIX_DESTRUCTIVE_COMMANDS = {
    "rm",
    "dd",
    "mkfs",
    "fdisk",
    "truncate",
    "sudo",
    "su",
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

DANGEROUS_GIT_REGEX = re.compile(r"\bgit\s+(?:push|reset\s+--hard|clean\s+-[a-zA-Z]*f[a-zA-Z]*)\b", re.I)
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


def _first_token(command: str) -> str:
    try:
        tokens = shlex.split(command, posix=not is_windows())
    except Exception:
        tokens = command.split()
    if not tokens:
        return ""
    token = tokens[0].strip().lower()
    if is_windows():
        token = ntpath.basename(token)
    else:
        token = os.path.basename(token)
    return token.removesuffix(".exe")


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
    Analyzes a shell command for safety before execution.

    This is intentionally conservative. It only catches obvious destructive
    commands and sensitive paths; it is not a sandbox.
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
            return False, f"Execution of potentially unsafe command: {base_bin}"

    return True, "Command is safe"


def analyze_bash_command(command: str) -> Tuple[bool, str]:
    return analyze_shell_command(command)
