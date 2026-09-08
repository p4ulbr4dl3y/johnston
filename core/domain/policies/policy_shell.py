"""Shell-command parsing helpers for the permission policy.

Moved verbatim from ``core.domain.policies.permission_policy``.
"""
import os
import platform
import re
import shlex
from typing import List, Optional

_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PREFIX_WRAPPERS = frozenset({"sudo", "env", "time", "nice", "nohup", "exec", "xargs"})
_WRAPPER_OPTS_WITH_ARG = frozenset({
    "-u",
    "-g",
    "-p",
    "-r",
    "-t",
    "-T",
    "-U",
    "-C",
    "-D",
    "-R",
    "-n",
    "-o",
    "-f",
    "-S",
    "-a",
    "--user",
    "--group",
    "--adjustment",
    "--chdir",
    "--unset",
    "--output",
    "--format",
})


def strip_wrapper_tokens(tokens: list[str]) -> list[str]:
    """Strip leading env assignments (VAR=val) and wrapper commands (sudo, env, nice, etc.) from token stream."""
    idx = 0
    while idx < len(tokens) and _ENV_VAR_RE.match(tokens[idx]):
        idx += 1

    while idx < len(tokens):
        cand = tokens[idx].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if cand.endswith(".exe"):
            cand = cand[:-4]
        if cand in _PREFIX_WRAPPERS:
            idx += 1
            while idx < len(tokens):
                tok = tokens[idx]
                if tok == "--":
                    idx += 1
                    break
                if _ENV_VAR_RE.match(tok):
                    idx += 1
                    continue
                if tok.startswith("-"):
                    if "=" in tok:
                        idx += 1
                    elif tok in _WRAPPER_OPTS_WITH_ARG:
                        idx += 2
                    else:
                        idx += 1
                    continue
                break
            continue
        break

    return tokens[idx:]


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

# Interpreter tokens (shells, python, node, ruby, perl, php) with optional
# versioned names and path prefixes: /bin/bash, /usr/bin/env bash, python3.13.
_INTERP_NAMES = frozenset(
    {
        "bash",
        "sh",
        "zsh",
        "dash",
        "pwsh",
        "powershell",
        "python",
        "python3",
        "python3.10",
        "python3.11",
        "python3.12",
        "python3.13",
        "node",
        "ruby",
        "perl",
        "php",
    }
)


def _is_interpreter_token(token: str) -> bool:
    """True when a command token is a known interpreter binary (path allowed)."""
    if not token:
        return False
    base = os.path.basename(token)
    return base in _INTERP_NAMES or bool(re.fullmatch(r"python\d+(?:\.\d+)?", base))


_UNSAFE_SHELL_REGEX = re.compile(
    r"(\$\(|`"
    r"|\b(?:bash|sh|zsh|dash|powershell|pwsh)\s+(?:-[ceElis]\b|-command\b|-encodedcommand\b|[^\s-])"
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
    """Detects unsafe/dynamic shell syntax that cannot be safely validated by static patterns.

    Conservative (fail-closed): a known interpreter token that appears in an
    invocable position — leading executable, after an env assignment, invoked
    via ``env``, or with combined/script flags — is treated as unsafe because
    the command string can inject code or load an attacker-controlled startup
    file. Compound commands are checked per subcommand.
    """
    if not cmd or not isinstance(cmd, str):
        return False
    if _UNSAFE_SHELL_REGEX.search(cmd):
        return True
    parts = extract_shell_subcommands(cmd)
    if len(parts) > 1:
        return any(has_unsafe_shell_syntax(p) for p in parts)
    if not parts:
        return False
    return _interpreter_invocation_unsafe(parts[0])


def _interpreter_invocation_unsafe(cmd: str) -> bool:
    """True when a single (non-compound) command invokes an interpreter in a
    way that can execute code or inject startup files."""
    try:
        tokens = shlex.split(cmd)
    except Exception:
        tokens = cmd.strip().split()
    if not tokens:
        return False

    idx = 0
    env_assigned = False
    n = len(tokens)
    while idx < n:
        tok = tokens[idx]
        if tok == "env":
            # env [-options] <command> — env itself is a wrapper; skip its flags
            idx += 1
            while idx < n and tokens[idx].startswith("-") and tokens[idx] != "-":
                idx += 1
            continue
        if "=" in tok and not tok.startswith("-"):
            env_assigned = True
            idx += 1
            continue
        if tok in _WRAPPER_COMMANDS:
            idx += 1
            continue
        break
    if idx >= n:
        return False

    binary = tokens[idx]
    if not _is_interpreter_token(binary):
        return False

    # Env assignment before an interpreter can inject startup files
    # (BASH_ENV=..., ENV=..., NODE_OPTIONS=..., PYTHONSTARTUP=...).
    if env_assigned:
        return True

    args = tokens[idx + 1 :]
    if not args:
        # Bare interpreter launch reads code from stdin / env startup files.
        return True
    if args[0] == "-m":
        # python -m <module> is a deterministic module invocation.
        return False
    for a in args:
        if a.startswith("-"):
            if binary in ("bash", "sh", "zsh", "dash", "pwsh", "powershell"):
                # Combined/script flags (-lc, -ec, -fc, -sc, -li, --login)
                # switch the shell to code/interactive/login mode.
                if re.search(r"[cei]", a):
                    return True
                continue
            # python/node/ruby/perl/php: explicit code flags.
            if a in ("-c", "-e", "--eval") or re.search(r"-[a-z0-9]*[cer]\b", a):
                return True
            continue
        # First non-flag argument is a script file: safe static invocation
        # (python script.py, python -u script.py).
        return False
    # All flags, no script/module: python -u (stdin code), node -i, etc.
    return True


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


_GIT_OPTS_WITH_ARG = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"})
_MUTATING_GIT = frozenset({
    "commit",
    "push",
    "checkout",
    "switch",
    "reset",
    "merge",
    "rebase",
    "revert",
    "clean",
    "cherry-pick",
    "restore",
    "rm",
    "mv",
    "pull",
    "apply",
    "stash",
    "init",
    "clone",
    "am",
    "format-patch",
    "repack",
    "prune",
    "gc",
})


def check_read_only_command_mutations(cmd: str) -> Optional[str]:
    """Inspect shell command for mutating operations in read-only mode using shlex."""
    is_win = platform.system() == "Windows"
    try:
        lexer = shlex.shlex(cmd, posix=not is_win, punctuation_chars=True)
        lexer.whitespace_split = True
        raw_tokens = [t.strip("\"'") for t in lexer]
    except Exception:
        raw_tokens = cmd.split()

    if not raw_tokens:
        return None

    # Strip grouping parentheses
    tokens = [t for t in raw_tokens if t not in ("(", ")")]

    subcmds: List[List[str]] = []
    curr: List[str] = []
    for tok in tokens:
        if tok in ("&&", ";", "|", "||", "&"):
            if curr:
                subcmds.append(curr)
                curr = []
        else:
            curr.append(tok)
    if curr:
        subcmds.append(curr)

    for sc in subcmds:
        if not sc:
            continue

        sc = strip_wrapper_tokens(sc)
        if not sc:
            continue

        idx = 0
        base = sc[idx].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if base.endswith(".exe"):
            base = base[:-4]

        if base == "git":
            i = idx + 1
            while i < len(sc):
                t = sc[i]
                if t.startswith("-"):
                    if "=" in t:
                        i += 1
                    elif t in _GIT_OPTS_WITH_ARG:
                        i += 2
                    else:
                        i += 1
                else:
                    t_low = t.lower()
                    if t_low in _MUTATING_GIT:
                        return f"git {t_low} is not permitted in read-only role"
                    if t_low == "branch":
                        has_list = any(x in ("-l", "--list", "-a", "-r", "--remotes", "--all") for x in sc[i + 1 :])
                        for b_tok in sc[i + 1 :]:
                            if b_tok in (
                                "-d",
                                "-D",
                                "-m",
                                "-M",
                                "-c",
                                "-C",
                                "--delete",
                                "--move",
                                "--copy",
                                "-u",
                                "--set-upstream-to",
                                "--unset-upstream",
                            ):
                                return f"git branch {b_tok} is not permitted in read-only role"
                            if not b_tok.startswith("-") and not has_list:
                                return "git branch creation is not permitted in read-only role"
                    elif t_low == "tag":
                        has_list = any(x in ("-l", "--list") for x in sc[i + 1 :])
                        for tag_tok in sc[i + 1 :]:
                            if tag_tok in ("-d", "--delete", "-a", "-s", "-u", "-f", "--force"):
                                return f"git tag {tag_tok} is not permitted in read-only role"
                            if not tag_tok.startswith("-") and not has_list:
                                return "git tag creation is not permitted in read-only role"
                    elif t_low == "remote":
                        for r_tok in sc[i + 1 :]:
                            if r_tok.lower() in (
                                "add",
                                "rename",
                                "remove",
                                "rm",
                                "set-url",
                                "set-head",
                                "set-branches",
                                "prune",
                            ):
                                return f"git remote {r_tok} is not permitted in read-only role"
                    break

        for t in sc:
            if t in (">", ">>", "1>", "2>"):
                return "file write redirects are not permitted in read-only role"

        if base in ("del", "erase", "rmdir", "rd", "move", "ren", "rename", "rm", "unlink", "truncate"):
            return f"mutating command {base} is not permitted in read-only role"

    return None

