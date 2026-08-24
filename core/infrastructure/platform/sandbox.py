"""Cross-platform sandbox execution helper for shell commands and file tools.

Provides lightweight OS-level isolation for shell tasks:
- macOS: uses /usr/bin/sandbox-exec with dynamically generated SBPL profiles.
- Linux: uses Bubblewrap (bwrap) with ro-bind / and bind workspace/tmp.
- Windows/other: graceful fallback.
"""
from __future__ import annotations

import os
import platform
import shutil
import tempfile
from typing import List, Optional, Tuple

from core.infrastructure.platform.platform_utils import shell_executable

_SEATBELT_EXE = "/usr/bin/sandbox-exec"


def is_sandbox_supported() -> bool:
    """Return True if OS-level sandboxing is supported on this host."""
    if platform.system() == "Darwin":
        return os.path.exists(_SEATBELT_EXE)
    if platform.system() == "Linux":
        return shutil.which("bwrap") is not None
    return False


def get_sandbox_backend_name() -> str:
    """Return the name of the sandbox backend available on this host."""
    if platform.system() == "Darwin" and os.path.exists(_SEATBELT_EXE):
        return "seatbelt"
    if platform.system() == "Linux" and shutil.which("bwrap") is not None:
        return "bubblewrap"
    return "none"


def is_path_writable_in_sandbox(
    path: str,
    cwd: Optional[str] = None,
    extra_writable_roots: Optional[List[str]] = None,
) -> bool:
    """Check if path is inside allowed writable roots in sandbox mode."""
    target_abs = os.path.realpath(os.path.abspath(path))
    workspace = os.path.realpath(os.path.abspath(cwd or os.getcwd()))

    allowed_roots = [workspace, "/tmp", "/private/tmp", "/dev"]
    sys_temp = tempfile.gettempdir()
    if sys_temp:
        allowed_roots.append(os.path.realpath(os.path.abspath(sys_temp)))

    if extra_writable_roots:
        for p in extra_writable_roots:
            allowed_roots.append(os.path.realpath(os.path.abspath(p)))

    for root in allowed_roots:
        clean_root = root.rstrip(os.sep)
        if target_abs == clean_root or target_abs.startswith(clean_root + os.sep):
            return True
    return False


def is_path_readable_in_sandbox(
    path: str,
    cwd: Optional[str] = None,
    extra_deny_read_paths: Optional[List[str]] = None,
) -> bool:
    """Check if path is allowed for reading in sandbox mode (blocks sensitive paths)."""
    target_abs = os.path.realpath(os.path.abspath(path))
    home = os.path.realpath(os.path.expanduser("~"))

    deny_roots = [
        os.path.join(home, ".ssh"),
        os.path.join(home, ".aws"),
        os.path.join(home, ".gnupg"),
    ]
    if extra_deny_read_paths:
        for p in extra_deny_read_paths:
            deny_roots.append(os.path.realpath(os.path.abspath(p)))

    for deny in deny_roots:
        deny_real = os.path.realpath(os.path.abspath(deny))
        clean_deny = deny_real.rstrip(os.sep)
        if target_abs == clean_deny or target_abs.startswith(clean_deny + os.sep):
            return False
    return True


def generate_seatbelt_profile(
    workspace_dir: str,
    extra_writable_roots: Optional[List[str]] = None,
    extra_deny_read_paths: Optional[List[str]] = None,
) -> str:
    """Generate macOS Seatbelt (SBPL) profile string allowing writes only in workspace, temp dirs, and /dev."""
    workspace_abs = os.path.abspath(workspace_dir)
    workspace_real = os.path.realpath(workspace_abs)

    writable_paths = [
        workspace_abs,
        workspace_real,
        "/tmp",
        "/private/tmp",
        "/dev",
    ]
    sys_temp = tempfile.gettempdir()
    if sys_temp:
        for t in (os.path.abspath(sys_temp), os.path.realpath(sys_temp)):
            if t not in writable_paths:
                writable_paths.append(t)

    if extra_writable_roots:
        for p in extra_writable_roots:
            p_abs = os.path.abspath(p)
            p_real = os.path.realpath(p_abs)
            for item in (p_abs, p_real):
                if item not in writable_paths:
                    writable_paths.append(item)

    home = os.path.expanduser("~")
    deny_reads = [
        os.path.join(home, ".ssh"),
        os.path.join(home, ".aws"),
        os.path.join(home, ".gnupg"),
    ]
    if extra_deny_read_paths:
        for p in extra_deny_read_paths:
            p_abs = os.path.abspath(p)
            p_real = os.path.realpath(p_abs)
            for item in (p_abs, p_real):
                if item not in deny_reads:
                    deny_reads.append(item)

    req_not_clauses = "\n        ".join(f'(require-not (subpath "{p}"))' for p in writable_paths)
    deny_read_clauses = "\n    ".join(f'(subpath "{p}")' for p in deny_reads)

    return f"""(version 1)
(allow default)
(deny file-write*
    (require-all
        {req_not_clauses}
    )
)
(deny file-read*
    {deny_read_clauses}
)
"""


def build_sandboxed_command(
    command: str,
    cwd: Optional[str] = None,
    extra_writable_roots: Optional[List[str]] = None,
) -> Tuple[str, List[str], bool]:
    """Wrap command with platform-specific sandbox if available.

    Returns:
        (executable, args_list, is_sandboxed)
    """
    workspace = cwd or os.getcwd()
    workspace_abs = os.path.realpath(os.path.abspath(workspace))
    shell = shell_executable() or "/bin/sh"

    if platform.system() == "Darwin" and os.path.exists(_SEATBELT_EXE):
        profile = generate_seatbelt_profile(workspace_abs, extra_writable_roots=extra_writable_roots)
        return (
            _SEATBELT_EXE,
            ["-p", profile, shell, "-c", command],
            True,
        )

    bwrap = shutil.which("bwrap")
    if platform.system() == "Linux" and bwrap is not None:
        bwrap_args = [
            "--ro-bind", "/", "/",
            "--bind", workspace_abs, workspace_abs,
            "--bind", "/tmp", "/tmp",
            "--dev", "/dev",
            "--proc", "/proc",
            "--unshare-pid",
        ]
        if os.path.exists("/var/tmp"):
            bwrap_args.extend(["--bind", "/var/tmp", "/var/tmp"])
        if extra_writable_roots:
            for extra in extra_writable_roots:
                extra_abs = os.path.realpath(os.path.abspath(extra))
                if os.path.exists(extra_abs):
                    bwrap_args.extend(["--bind", extra_abs, extra_abs])
        bwrap_args.extend(["--", shell, "-c", command])
        return (bwrap, bwrap_args, True)

    # Windows or unsupported platform: no wrapping
    return (shell, ["-c", command], False)
