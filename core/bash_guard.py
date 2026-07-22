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
    Анализирует bash-команду на безопасность.
    Возвращает (is_safe, reason).
    """
    cmd_str = command.strip()
    if not cmd_str:
        return True, "Пустая команда"

    # 1. Проверка на реддиректы записи (>, >>, &>, 2>)
    if REDIRECTION_REGEX.search(cmd_str):
        return False, "Перенаправление вывода в файл (> или >>)"

    # 2. Проверка на подоболочки и подстановку команд $(...) или `...`
    if SUBSHELL_REGEX.search(cmd_str):
        return False, "Выполнение команд внутри подоболочки $() или ``"

    # 3. Проверка опасных git-команд
    if MUTATING_GIT_REGEX.search(cmd_str):
        return False, "Мутирующая операция Git (push, reset, clean, etc.)"

    # 4. Проверка чувствительных системных путей
    for path in SENSITIVE_PATHS:
        if path in cmd_str:
            return False, f"Доступ к чувствительному системному пути ({path})"

    # 5. Разделение цепочки команд (; , &&, ||, |)
    # Заменяем операторы цепочки на единый разделитель
    cmd_chain = re.split(r";|&&|\|\||\|", cmd_str)

    for sub_cmd in cmd_chain:
        sub_cmd = sub_cmd.strip()
        if not sub_cmd:
            continue

        try:
            tokens = shlex.split(sub_cmd)
        except Exception:
            return False, "Не удалось спарсить синтаксис команды"

        if not tokens:
            continue

        base_bin = tokens[0]

        # Если прямое упоминание деструктивных команд
        if base_bin in DESTRUCTIVE_COMMANDS:
            return False, f"Выполнение потенц. опасной или изменяющей команды: {base_bin}"

        # Проверка git подкоманд
        if base_bin == "git":
            full_git = " ".join(tokens[:2]) if len(tokens) >= 2 else "git"
            if full_git not in {"git status", "git diff", "git log", "git show", "git branch"}:
                return False, f"Операция Git под подтверждение: {full_git}"
            continue

        # Проверка одиночных безопасных команд
        if base_bin not in SAFE_SINGLE_COMMANDS:
            return False, f"Команда не из списка безопасных для автозапуска: {base_bin}"

    return True, "Команда безопасна"
