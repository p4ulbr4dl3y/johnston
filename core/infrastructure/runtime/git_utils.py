"""
Git Utilities for Johnston.
Provides unified git command execution with timeout handling and process safety.
"""

import asyncio
import difflib
import os
import re
import subprocess
import tempfile
from typing import List, Optional


def run_git(
    args: List[str],
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Executes a git command safely with optional timeout and environment overrides."""
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args=["git"] + args, returncode=124, stdout="", stderr="timeout")
    except Exception as e:
        return subprocess.CompletedProcess(args=["git"] + args, returncode=1, stdout="", stderr=str(e))


async def run_git_async(
    args: List[str],
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Runs ``run_git`` off the event loop via ``asyncio.to_thread``.

    Git commands carry timeouts (5-15s) and must never be awaited synchronously
    on the event loop, so async callers should use this wrapper.
    """
    return await asyncio.to_thread(run_git, args, cwd, env, timeout)


def is_git_repository(cwd: Optional[str] = None) -> bool:
    """Returns True if ``cwd`` (default: process cwd) is inside a git working tree."""
    res = run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd, timeout=5)
    return res.returncode == 0 and res.stdout.strip() == "true"


def format_git_branch_info(cwd: Optional[str] = None) -> str:
    """Returns a human-readable git branch string for a working directory.

    ``<name>`` when on a branch, ``detached HEAD (<sha>)`` when not,
    or ``""`` when the directory is not a git repo. Pure git-format knowledge
    kept in infrastructure (used by the prompt builder's system prompt).
    """
    res = run_git(["branch", "--show-current"], cwd=cwd, timeout=1)
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()

    rev_res = run_git(["rev-parse", "--short", "HEAD"], cwd=cwd, timeout=1)
    if rev_res.returncode == 0 and rev_res.stdout.strip():
        return f"detached HEAD ({rev_res.stdout.strip()})"
    return ""


def _content_to_text(content: str | list[str]) -> str:
    """Converts content to raw text, preserving a bare trailing newline."""
    if isinstance(content, list):
        return "\n".join(content)
    return content


def _relabel_diff(diff_text: str, fromfile: str, tofile: str) -> str:
    """Rewrites the temp paths in a `--no-index` diff to the caller's file labels.

    The temp files are always named ``old``/``new``, so git emits headers like
    ``--- a/<tmp>/old`` and ``+++ b/<tmp>/new``. Those are rewritten to the
    supplied ``fromfile``/``tofile`` labels.

    On Windows, temp paths contain ``:`` so git quotes the header paths
    (``--- "a/C:\\...\\old"``); those quotes are stripped by the relabel.

    Drops ``diff --git`` / ``index`` metadata headers, which are token cost
    for the agent and not needed for rendering.
    """
    out_lines = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git ") or line.startswith("index "):
            continue
        stripped = line.strip().replace('"', "")
        if re.search(r"^--- a[\\/][^\"']*[\\/]old$", stripped):
            line = f"--- {fromfile}"
        elif re.search(r"^\+\+\+ b[\\/][^\"']*[\\/]new$", stripped):
            line = f"+++ {tofile}"
        out_lines.append(line)
    return "\n".join(out_lines) + ("\n" if diff_text.endswith("\n") else "")


def make_git_diff(
    old_content: str | list[str],
    new_content: str | list[str],
    fromfile: str = "old",
    tofile: str = "new",
    context: int = 3,
) -> str:
    """Generates a unified diff using `git diff --no-index` (patience algorithm).

    Falls back to difflib when git is unavailable or produces unusable output.
    Returns an empty string when the contents are identical.
    """
    fromfile = fromfile or "old"
    tofile = tofile or "new"
    old_text = _content_to_text(old_content)
    new_text = _content_to_text(new_content)

    if old_text == new_text:
        return ""

    try:
        with tempfile.TemporaryDirectory() as tmp:
            old_path = os.path.join(tmp, "old")
            new_path = os.path.join(tmp, "new")
            with open(old_path, "w", encoding="utf-8") as f:
                f.write(old_text)
            with open(new_path, "w", encoding="utf-8") as f:
                f.write(new_text)
            res = run_git(
                [
                    "diff",
                    "--no-index",
                    "--no-color",
                    "--patience",
                    f"--unified={context}",
                    old_path,
                    new_path,
                ]
            )
            # --no-index returns 1 when differences exist, 0 when identical.
            if res.returncode not in (0, 1):
                raise RuntimeError(f"git diff failed: rc={res.returncode} stderr={res.stderr}")
            out = res.stdout
            if not out.strip():
                return ""
            return _relabel_diff(out, fromfile, tofile)
    except Exception:
        diff_lines = list(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile=fromfile,
                tofile=tofile,
                lineterm="",
                n=context,
            )
        )
        return "\n".join(diff_lines)
