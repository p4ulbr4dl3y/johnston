import re
import shlex
from typing import Tuple

DESTRUCTIVE_COMMANDS = {
    "rm", "dd", "mkfs", "fdisk", "truncate",
    "sudo", "su", "chmod", "chown",
    "reboot", "shutdown"
}

DANGEROUS_GIT_REGEX = re.compile(r"\bgit\s+(?:push|reset\s+--hard|clean\s+-[a-zA-Z]*f[a-zA-Z]*)\b")

SENSITIVE_PATHS = [
    "/etc", "/sys", "/proc", "/root", "~/.ssh"
]


def analyze_bash_command(command: str) -> Tuple[bool, str]:
    """
    Analyzes bash command for safety.
    Returns (is_safe, reason).
    """
    cmd_str = command.strip()
    if not cmd_str:
        return True, "Empty command"

    # 1. Check for dangerous Git operations (push, reset --hard, clean -f)
    if DANGEROUS_GIT_REGEX.search(cmd_str):
        return False, "Potentially dangerous Git operation (push, reset --hard, clean -f)"

    # 2. Check for sensitive system paths
    for path in SENSITIVE_PATHS:
        if path in cmd_str:
            return False, f"Access to sensitive system path ({path})"

    # 3. Split command chain (; , &&, ||, |)
    cmd_chain = re.split(r";|&&|\|\||\|", cmd_str)

    for sub_cmd in cmd_chain:
        sub_cmd = sub_cmd.strip()
        if not sub_cmd:
            continue

        try:
            tokens = shlex.split(sub_cmd)
        except Exception:
            return False, "Failed to parse command syntax"

        if not tokens:
            continue

        base_bin = tokens[0]

        # Check for direct destructive commands
        if base_bin in DESTRUCTIVE_COMMANDS:
            return False, f"Execution of potentially unsafe command: {base_bin}"

    return True, "Command is safe"

