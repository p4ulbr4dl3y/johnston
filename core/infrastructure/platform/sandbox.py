"""Cross-platform sandbox execution helper for shell commands and file tools.

Provides lightweight OS-level isolation for shell tasks:
- macOS: uses /usr/bin/sandbox-exec with dynamically generated SBPL profiles.
- Linux: uses Bubblewrap (bwrap) with ro-bind / and bind workspace/tmp.
- Windows: uses a restricted-token runner (CreateRestrictedToken + CreateProcessAsUserW)
  for privilege isolation. Note: unlike Seatbelt/bubblewrap this does NOT provide
  filesystem confinement; sensitive-path read and workspace-write policies are
  enforced at the tool layer (tools/read.py, tools/edit.py, tools/create.py).
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import tempfile
from typing import Callable, Dict, List, Optional, Tuple

from core.infrastructure.platform.platform_utils import shell_executable

logger = logging.getLogger(__name__)

_SEATBELT_EXE = "/usr/bin/sandbox-exec"

# Cache for bwrap usability probes: {realpath: bool}. Probing runs `bwrap --true`
# because a present-but-unusable binary (no userns/setuid) would otherwise fail
# every command at spawn time with an opaque namespace error.
_bwrap_probe_cache: Dict[str, bool] = {}


def _check_bwrap(bwrap_path: str) -> bool:
    """Return True if the bwrap binary can actually create its namespaces."""
    real = os.path.realpath(bwrap_path)
    if real in _bwrap_probe_cache:
        return _bwrap_probe_cache[real]
    try:
        proc = subprocess.run(
            [bwrap_path, "--ro-bind", "/", "/", "/bin/true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        usable = proc.returncode == 0
    except Exception:
        usable = False
    _bwrap_probe_cache[real] = usable
    if not usable:
        logger.warning("bwrap found at %s but cannot create namespaces (userns/setuid blocked)", bwrap_path)
    return usable


def is_sandbox_supported() -> bool:
    """Return True if OS-level sandboxing is supported on this host."""
    if platform.system() == "Darwin":
        return os.path.exists(_SEATBELT_EXE)
    if platform.system() == "Linux":
        bwrap = shutil.which("bwrap")
        return bwrap is not None and _check_bwrap(bwrap)
    if platform.system() == "Windows":
        return True
    return False


def get_sandbox_backend_name() -> str:
    """Return the name of the sandbox backend available on this host."""
    if platform.system() == "Darwin" and os.path.exists(_SEATBELT_EXE):
        return "seatbelt"
    if platform.system() == "Linux" and is_sandbox_supported():
        return "bubblewrap"
    if platform.system() == "Windows":
        return "windows_safer"
    return "none"


def get_default_deny_read_paths() -> List[str]:
    """Return sensitive credential paths blocked in sandbox mode across platforms."""
    home = os.path.expanduser("~")
    paths = [
        # SSH & GPG keys
        os.path.join(home, ".ssh"),
        os.path.join(home, ".gnupg"),
        # Cloud providers & clusters
        os.path.join(home, ".aws"),
        os.path.join(home, ".azure"),
        os.path.join(home, ".kube"),
        os.path.join(home, ".config", "gcloud"),
        # Git & CLI credentials
        os.path.join(home, ".config", "gh"),
        os.path.join(home, ".git-credentials"),
        os.path.join(home, ".netrc"),
        os.path.join(home, ".docker", "config.json"),
        os.path.join(home, ".vault-token"),
        os.path.join(home, ".terraform.d"),
        os.path.join(home, ".terraform.rc"),
        # Package registries & publishing tokens
        os.path.join(home, ".npmrc"),
        os.path.join(home, ".pypirc"),
        os.path.join(home, ".cargo", "credentials.toml"),
        os.path.join(home, ".gem", "credentials"),
        # Shell history
        os.path.join(home, ".bash_history"),
        os.path.join(home, ".zsh_history"),
        # Application secrets and global permissions
        os.path.join(home, ".johnston", "config.json"),
        os.path.join(home, ".johnston", "secrets.json"),
    ]

    # OS-specific credential locations
    if platform.system() == "Darwin":
        paths.append(os.path.join(home, "Library", "Keychains"))
    elif platform.system() == "Linux":
        paths.extend(["/etc/shadow", "/etc/gshadow", os.path.join(home, ".local", "share", "keyrings")])
    elif platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            paths.extend([
                os.path.join(appdata, "GitHub CLI"),
                os.path.join(appdata, "gcloud"),
            ])
        localappdata = os.environ.get("LOCALAPPDATA", "")
        if localappdata:
            paths.append(os.path.join(localappdata, "Microsoft", "Credentials"))

    return paths


def _is_fs_root(norm_path: str) -> bool:
    """True if a normcased path represents a filesystem root ('/' or 'C:\\')."""
    drive, tail = os.path.splitdrive(norm_path)
    return (not drive and tail == os.sep) or (bool(drive) and tail in ("", os.sep))


def is_path_writable_in_sandbox(
    path: str,
    cwd: Optional[str] = None,
    extra_writable_roots: Optional[List[str]] = None,
    allow_workspace_writes: bool = True,
) -> bool:
    """Check if path is inside allowed writable roots in sandbox mode."""
    target_abs = os.path.realpath(os.path.abspath(path))
    target_norm = os.path.normcase(target_abs)
    workspace = os.path.realpath(os.path.abspath(cwd or os.getcwd()))
    ws_norm = os.path.normcase(workspace)

    raw_roots: List[str] = []
    if platform.system() != "Windows":
        raw_roots.extend(["/tmp", "/private/tmp", "/dev"])
    if allow_workspace_writes:
        raw_roots.append(workspace)
    sys_temp = tempfile.gettempdir()
    if sys_temp:
        raw_roots.append(sys_temp)

    if extra_writable_roots:
        raw_roots.extend(extra_writable_roots)

    for r in raw_roots:
        if not r:
            continue
        root_real = os.path.realpath(os.path.abspath(r))
        root_norm = os.path.normcase(root_real)
        # A filesystem-root entry must never grant blanket write access; grant
        # everything only when the workspace itself IS the filesystem root.
        if _is_fs_root(root_norm):
            if root_norm == ws_norm and allow_workspace_writes:
                return True
            continue
        clean_root = root_norm.rstrip(os.sep)
        if target_norm == clean_root or target_norm.startswith(clean_root + os.sep):
            return True
    return False


def is_path_readable_in_sandbox(
    path: str,
    cwd: Optional[str] = None,
    extra_deny_read_paths: Optional[List[str]] = None,
) -> bool:
    """Check if path is allowed for reading in sandbox mode (blocks sensitive paths)."""
    target_abs = os.path.realpath(os.path.abspath(path))
    target_norm = os.path.normcase(target_abs)
    deny_roots = get_default_deny_read_paths()

    if extra_deny_read_paths:
        for p in extra_deny_read_paths:
            deny_roots.append(p)

    for deny in deny_roots:
        deny_abs = os.path.abspath(deny)
        deny_real = os.path.realpath(deny_abs)
        for d in (deny_abs, deny_real):
            clean_deny = os.path.normcase(d).rstrip(os.sep)
            if target_norm == clean_deny or target_norm.startswith(clean_deny + os.sep):
                return False
    return True


def _escape_sbpl_path(path_str: str) -> str:
    """Escape quotes and backslashes for Seatbelt SBPL strings."""
    return path_str.replace("\\", "\\\\").replace('"', '\\"')


def generate_seatbelt_profile(
    workspace_dir: str,
    extra_writable_roots: Optional[List[str]] = None,
    extra_deny_read_paths: Optional[List[str]] = None,
    allow_workspace_writes: bool = True,
    sys_temp: Optional[str] = None,
) -> str:
    """Generate macOS Seatbelt (SBPL) profile string allowing writes only in workspace, temp dirs, and /dev."""
    workspace_abs = os.path.abspath(workspace_dir)
    workspace_real = os.path.realpath(workspace_abs)

    writable_paths = [
        "/tmp",
        "/private/tmp",
        "/dev",
    ]
    if allow_workspace_writes:
        writable_paths.extend([workspace_abs, workspace_real])
    sys_temp = sys_temp or tempfile.gettempdir()
    if sys_temp:
        for t in (os.path.abspath(sys_temp), os.path.realpath(sys_temp)):
            if t not in writable_paths and not _is_fs_root(os.path.normcase(os.path.realpath(t))):
                writable_paths.append(t)

    if extra_writable_roots:
        for p in extra_writable_roots:
            p_abs = os.path.abspath(p)
            p_real = os.path.realpath(p_abs)
            for item in (p_abs, p_real):
                if item not in writable_paths and not _is_fs_root(os.path.normcase(item)):
                    writable_paths.append(item)

    deny_reads = get_default_deny_read_paths()
    if extra_deny_read_paths:
        for p in extra_deny_read_paths:
            deny_reads.append(p)

    deny_read_entries = []
    for p in deny_reads:
        p_abs = os.path.abspath(p)
        p_real = os.path.realpath(p_abs)
        for item in (p_abs, p_real):
            if item not in deny_read_entries:
                deny_read_entries.append(item)

    req_not_clauses = "\n        ".join(f'(require-not (subpath "{_escape_sbpl_path(p)}"))' for p in writable_paths)
    deny_read_clauses = "\n    ".join(f'(subpath "{_escape_sbpl_path(p)}")' for p in deny_read_entries)

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


def _build_bwrap_args(
    workspace_abs: str,
    allow_workspace_writes: bool = True,
    extra_writable_roots: Optional[List[str]] = None,
    deny_reads: Optional[List[str]] = None,
    sys_temp: Optional[str] = None,
    exists: Callable[[str], bool] = os.path.exists,
) -> List[str]:
    """Build the bubblewrap argv (without the binary itself and trailing command)."""
    workspace_bind = (
        ["--bind", workspace_abs, workspace_abs]
        if allow_workspace_writes
        else ["--ro-bind", workspace_abs, workspace_abs]
    )
    bwrap_args = [
        "--ro-bind", "/", "/",
        *workspace_bind,
        "--bind", "/tmp", "/tmp",
        "--dev", "/dev",
        "--proc", "/proc",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
    ]
    if exists("/var/tmp"):
        bwrap_args.extend(["--bind", "/var/tmp", "/var/tmp"])

    # Honor TMPDIR pointing outside /tmp//var/tmp/workspace (e.g. ~/.cache/tmp),
    # otherwise temp-file usage inside the sandbox fails closed.
    bound_rw = {"/tmp", "/var/tmp", workspace_abs}
    candidates: List[str] = []
    if sys_temp:
        candidates.append(sys_temp)
    if extra_writable_roots:
        candidates.extend(extra_writable_roots)
    for extra in candidates:
        extra_abs = os.path.realpath(os.path.abspath(extra))
        if not exists(extra_abs):
            continue
        if _is_fs_root(os.path.normcase(extra_abs)):
            # Never mount the filesystem root rw: that would disable confinement.
            continue
        if any(extra_abs == b or extra_abs.startswith(b.rstrip(os.sep) + os.sep) for b in bound_rw):
            continue
        bwrap_args.extend(["--bind", extra_abs, extra_abs])
        bound_rw.add(extra_abs)

    for d in deny_reads or []:
        d_abs = os.path.realpath(os.path.abspath(d))
        if os.path.isdir(d_abs):
            bwrap_args.extend(["--tmpfs", d_abs])
        elif os.path.isfile(d_abs):
            bwrap_args.extend(["--ro-bind", "/dev/null", d_abs])

    return bwrap_args


def build_sandboxed_command(
    command: str,
    cwd: Optional[str] = None,
    extra_writable_roots: Optional[List[str]] = None,
    extra_deny_read_paths: Optional[List[str]] = None,
    allow_workspace_writes: bool = True,
) -> Tuple[str, List[str], bool]:
    """Wrap command with platform-specific sandbox if available.

    Returns:
        (executable, args_list, is_sandboxed)
    """
    workspace = cwd or os.getcwd()
    workspace_abs = os.path.realpath(os.path.abspath(workspace))
    shell = shell_executable() or "/bin/sh"

    if platform.system() == "Darwin" and os.path.exists(_SEATBELT_EXE):
        profile = generate_seatbelt_profile(
            workspace_abs,
            extra_writable_roots=extra_writable_roots,
            extra_deny_read_paths=extra_deny_read_paths,
            allow_workspace_writes=allow_workspace_writes,
        )
        return (
            _SEATBELT_EXE,
            ["-p", profile, shell, "-c", command],
            True,
        )

    bwrap = shutil.which("bwrap") if platform.system() == "Linux" else None
    if bwrap is not None and _check_bwrap(bwrap):
        deny_reads = list(get_default_deny_read_paths())
        if extra_deny_read_paths:
            deny_reads.extend(extra_deny_read_paths)

        bwrap_args = _build_bwrap_args(
            workspace_abs,
            allow_workspace_writes=allow_workspace_writes,
            extra_writable_roots=extra_writable_roots,
            deny_reads=deny_reads,
        )
        bwrap_args.extend(["--", shell, "-c", command])
        return (bwrap, bwrap_args, True)

    if platform.system() == "Windows":
        import sys

        # Launch by absolute script path: `python -m` resolves modules from the
        # child's cwd (= user workspace) where the `core` package does not exist.
        runner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "win_sandbox_runner.py")
        args = [runner_path, "--command", command]
        if cwd:
            args.extend(["--cwd", os.path.realpath(os.path.abspath(cwd))])
        return (
            sys.executable,
            args,
            True,
        )

    # Unsupported platform: no wrapping.
    logger.warning("sandbox requested but unsupported on %s; running unsandboxed", platform.system())
    return (shell, ["-c", command], False)
