import re
import shlex
from typing import Tuple

SAFE_BASE_COMMANDS = {
    "ls", "pwd", "cat", "grep", "egrep", "fgrep", "find", "which",
    "head", "tail", "wc", "whoami", "date", "echo", "printf", "diff",
    "git status", "git diff", "git log", "git show", "git branch",
    "pytest", "ruff check", "flake8", "mypy", "python -m unittest"
}

SAFE_SINGLE_COMMANDS = {
    "ls", "pwd", "cat", "grep", "egrep", "fgrep", "find", "which",
    "head", "tail", "wc", "whoami", "date", "echo", "printf", "diff",
    "env", "printenv", "uname", "uptime", "du", "df"
}

REDIRECTION_REGEX = re.compile(r"(?:\d*>|&>|>>|>\|)")
SUBSHELL_REGEX = re.compile(r"(?:\$\(|=|`|\$\{)")
MUTATING_GIT_REGEX = re.compile(r"\bgit\s+(?:push|reset|clean|rebase|commit|checkout|merge|branch\s+-[dD])\b")
DESTRUCTIVE_COMMANDS = {
    "rm", "mv", "chmod", "chown", "truncate", "dd", "mkfs", "fdisk",
    "sudo", "su", "systemctl", "service", "reboot", "shutdown",
    "kill", "killall", "pkill", "python", "python3", "uv", "pip",
    "npm", "yarn", "pnpm", "cargo", "make", "gcc", "g++", "go"
}

SENSITIVE_PATHS = [
    "/etc", "/sys", "/proc", "/var", "/usr", "/boot", "/root",
    "~/.ssh", "~/.bashrc", "~/.zshrc", "~/.config"
]


def analyze_bash_command(command: str) -> Tuple[bool, str]:
    """
    Analyzes bash command for safety.
    Returns (is_safe, reason).
    """
    cmd_str = command.strip()
    if not cmd_str:
        return True, "Empty command"

    # 1. Check for output redirection (>, >>, &>, 2>)
    if REDIRECTION_REGEX.search(cmd_str):
        return False, "Output redirection to file (> or >>)"

    # 2. Check for subshells and command substitution $(...) or `...`
    if SUBSHELL_REGEX.search(cmd_str):
        return False, "Execution of commands inside subshell $() or ``"

    # 3. Check for mutating Git commands
    if MUTATING_GIT_REGEX.search(cmd_str):
        return False, "Mutating Git operation (push, reset, clean, etc.)"

    # 4. Check for sensitive system paths
    for path in SENSITIVE_PATHS:
        if path in cmd_str:
            return False, f"Access to sensitive system path ({path})"

    # 5. Split command chain (; , &&, ||, |)
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
            return False, f"Execution of potentially unsafe or mutating command: {base_bin}"

        # Check Git subcommands
        if base_bin == "git":
            full_git = " ".join(tokens[:2]) if len(tokens) >= 2 else "git"
            if full_git not in {"git status", "git diff", "git log", "git show", "git branch"}:
                return False, f"Git operation requiring confirmation: {full_git}"
            continue

        # Check safe single commands
        if base_bin not in SAFE_SINGLE_COMMANDS:
            return False, f"Command not in safe auto-execute list: {base_bin}"

    return True, "Command is safe"
