"""Secrets-file helpers for the permission policy.

These helpers were moved out of ``core.domain.policies.permission_policy``
to reduce the facade module's size. They read ``LOGS_DIR`` and
``SECRETS_FILE`` dynamically from the facade module (``_pp``) so that
tests monkeypatching ``permission_policy.LOGS_DIR`` / ``permission_policy.SECRETS_FILE``
keep working.
"""
import fnmatch
import os
import re
import shlex
from typing import List, Optional

from core.domain.policies import permission_policy as _pp


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
    if _pp.LOGS_DIR and str(_pp.LOGS_DIR) not in roots:
        roots.append(str(_pp.LOGS_DIR))
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
    if _pp.SECRETS_FILE and str(_pp.SECRETS_FILE) not in candidates:
        candidates.append(str(_pp.SECRETS_FILE))
    default_sec = os.path.expanduser("~/.johnston/secrets.json")
    if default_sec not in candidates:
        candidates.append(default_sec)
    return candidates


def get_secrets_file() -> str:
    """Returns path to the centralized secrets file."""
    files = get_secrets_files()
    return files[0] if files else _pp.SECRETS_FILE


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

    subcmds = _pp.extract_shell_subcommands(command) or [command]
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
