"""Command sanitization utilities for shell execution and permission enforcement."""

import io
import os
import re
import shlex
from typing import Optional

from johnston.core.domain.policies.policy_shell import (
    _ENV_VAR_RE,
    _PREFIX_WRAPPERS,
    _WRAPPER_OPTS_WITH_ARG,
    strip_wrapper_tokens,
)

_REDUNDANT_CD_PATTERN = re.compile(r"^\s*cd\s+(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))\s*(?:&&|;)\s*")
_STANDALONE_CD_PATTERN = re.compile(r"^\s*cd(?:\s+(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+)))?\s*$")


def clean_cd_command(cmd: str, workspace_dir: str) -> tuple[str, Optional[str]]:
    """Clean redundant cd commands and catch unsupported standalone cd calls.

    Returns:
        (cleaned_cmd, error_message_or_none)
    """
    cleaned = cmd.strip()
    norm_ws = os.path.normcase(os.path.realpath(os.path.abspath(workspace_dir)))

    while True:
        m = _REDUNDANT_CD_PATTERN.match(cleaned)
        if not m:
            break
        target = m.group(1) or m.group(2) or m.group(3)
        norm_target = os.path.normpath(target.replace("\\", "/"))
        if norm_target == ".":
            cleaned = cleaned[m.end() :].strip()
            continue
        try:
            abs_target = os.path.realpath(os.path.abspath(os.path.join(workspace_dir, target)))
            if os.path.normcase(abs_target) == norm_ws:
                cleaned = cleaned[m.end() :].strip()
                continue
        except Exception:
            pass
        break

    m_alone = _STANDALONE_CD_PATTERN.match(cleaned)
    if m_alone:
        target = m_alone.group(1) or m_alone.group(2) or m_alone.group(3)
        # Standalone `cd .` or `cd .\` is allowed as no-op (used on Windows/tests)
        if target is not None and os.path.normpath(target.replace("\\", "/")) == ".":
            return (cleaned, None)
        return (
            cleaned,
            "Directory changes via 'cd' do not persist across shell calls. Shell runs in project root by default. Use 'cwd' parameter to run in a subdirectory.",
        )

    return (cleaned, None)



def _clean_one_command_segment(cmd_segment: str) -> str:
    try:
        s = shlex.shlex(io.StringIO(cmd_segment), posix=True, punctuation_chars=True)
        tokens_with_pos: list[tuple[str, int]] = []
        while True:
            pos = s.instream.tell()
            tok = s.get_token()
            if not tok:
                break
            tokens_with_pos.append((tok, pos))
    except Exception:
        return cmd_segment.strip()

    if not tokens_with_pos:
        return cmd_segment.strip()

    tokens = [t for t, _ in tokens_with_pos]
    stripped = strip_wrapper_tokens(tokens)
    if not stripped:
        return ""
    if len(stripped) == len(tokens):
        return cmd_segment.strip()

    first_kept_idx = len(tokens) - len(stripped)
    _, start_pos = tokens_with_pos[first_kept_idx]
    return cmd_segment[start_pos:].strip()


def _split_command_operators(cmd: str) -> list[str]:
    """Split cmd into segments and operators (&&, ||, ;, |, &) respecting quotes and escapes."""
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    escape = False
    i = 0
    n = len(cmd)

    while i < n:
        c = cmd[i]
        if escape:
            current.append(c)
            escape = False
            i += 1
            continue

        if c == "\\":
            current.append(c)
            escape = True
            i += 1
            continue

        if c == "'" and not in_double:
            in_single = not in_single
            current.append(c)
            i += 1
            continue

        if c == '"' and not in_single:
            in_double = not in_double
            current.append(c)
            i += 1
            continue

        if not in_single and not in_double:
            if i + 1 < n and cmd[i : i + 2] in ("&&", "||"):
                if current:
                    segments.append("".join(current))
                    current = []
                segments.append(cmd[i : i + 2])
                i += 2
                continue
            if c in (";", "&", "|"):
                if current:
                    segments.append("".join(current))
                    current = []
                segments.append(c)
                i += 1
                continue

        current.append(c)
        i += 1

    if current:
        segments.append("".join(current))

    return segments


def clean_command_wrappers(cmd: str) -> str:
    """Strip leading environment variables and prefix wrappers (sudo, env, nice, etc.) from a shell command."""
    if not cmd or not isinstance(cmd, str):
        return ""
    cleaned = cmd.strip()
    if not cleaned:
        return ""

    parts = _split_command_operators(cleaned)
    cleaned_parts: list[str] = []
    for part in parts:
        if part in ("&&", "||", ";", "&", "|"):
            cleaned_parts.append(part)
        elif not part.strip():
            continue
        else:
            c = _clean_one_command_segment(part)
            if c:
                cleaned_parts.append(c)

    return " ".join(cleaned_parts).strip()


__all__ = [
    "_REDUNDANT_CD_PATTERN",
    "_STANDALONE_CD_PATTERN",
    "clean_cd_command",
    "_ENV_VAR_RE",
    "_PREFIX_WRAPPERS",
    "_WRAPPER_OPTS_WITH_ARG",
    "strip_wrapper_tokens",
    "clean_command_wrappers",
]
