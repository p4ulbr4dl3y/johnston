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
_seatbelt_probe_cache: Dict[str, bool] = {}


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


def _check_seatbelt(seatbelt_path: str) -> bool:
    """Return True if sandbox-exec can actually apply profiles (fails under nested sandbox)."""
    real = os.path.realpath(seatbelt_path)
    if real in _seatbelt_probe_cache:
        return _seatbelt_probe_cache[real]
    if not os.path.exists(seatbelt_path):
        _seatbelt_probe_cache[real] = False
        return False
    try:
        proc = subprocess.run(
            [seatbelt_path, "-p", "(version 1)(allow default)", "/usr/bin/true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        usable = proc.returncode == 0
    except Exception:
        usable = False
    _seatbelt_probe_cache[real] = usable
    if not usable:
        logger.warning("sandbox-exec found at %s but cannot apply profiles (nested sandbox/blocked)", seatbelt_path)
    return usable


def is_sandbox_supported() -> bool:
    """Return True if OS-level sandboxing is supported on this host."""
    if platform.system() == "Darwin":
        return os.path.exists(_SEATBELT_EXE) and _check_seatbelt(_SEATBELT_EXE)
    if platform.system() == "Linux":
        bwrap = shutil.which("bwrap")
        return bwrap is not None and _check_bwrap(bwrap)
    if platform.system() == "Windows":
        return True
    return False


_cached_default_deny_paths: Optional[List[str]] = None


def get_default_deny_read_paths() -> List[str]:
    """Return sensitive credential paths blocked in sandbox mode across platforms."""
    global _cached_default_deny_paths
    if _cached_default_deny_paths is not None:
        return list(_cached_default_deny_paths)

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

    _cached_default_deny_paths = paths
    return list(_cached_default_deny_paths)


def _is_fs_root(norm_path: str) -> bool:
    """True if a normcased path represents a filesystem root ('/' or 'C:\\')."""
    drive, tail = os.path.splitdrive(norm_path)
    return (not drive and tail == os.sep) or (bool(drive) and tail in ("", os.sep))


def get_git_worktree_writable_roots(workspace: str) -> List[str]:
    """If workspace is a linked git worktree, return the gitdir and commondir paths."""
    if not workspace:
        return []
    git_file = os.path.join(workspace, ".git")
    if not os.path.isfile(git_file):
        return []
    try:
        with open(git_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content.startswith("gitdir:"):
            raw_gitdir = content[len("gitdir:") :].strip()
            if not os.path.isabs(raw_gitdir):
                raw_gitdir = os.path.normpath(os.path.join(workspace, raw_gitdir))
            gitdir = os.path.realpath(raw_gitdir)
            if not os.path.isdir(gitdir) or not os.path.isfile(os.path.join(gitdir, "HEAD")):
                return []
            if not is_path_readable_in_sandbox(gitdir, cwd=workspace) or _is_fs_root(os.path.normcase(gitdir)):
                return []

            roots = [gitdir]
            commondir_file = os.path.join(gitdir, "commondir")
            if os.path.isfile(commondir_file):
                with open(commondir_file, "r", encoding="utf-8") as cf:
                    raw_common = cf.read().strip()
                if not os.path.isabs(raw_common):
                    raw_common = os.path.normpath(os.path.join(gitdir, raw_common))
                common_dir = os.path.realpath(raw_common)
                if (
                    os.path.isdir(common_dir)
                    and os.path.isdir(os.path.join(common_dir, "objects"))
                    and is_path_readable_in_sandbox(common_dir, cwd=workspace)
                    and not _is_fs_root(os.path.normcase(common_dir))
                ):
                    if common_dir not in roots:
                        roots.append(common_dir)
            return roots
    except Exception:
        pass
    return []


def get_default_writable_cache_roots() -> List[str]:
    """Return common user cache roots (e.g. ~/.cache, ~/.npm, ~/.cargo/registry, UV_CACHE_DIR) for build tools & linters."""
    roots: List[str] = []

    # Environment variables overrides
    cache_env_vars = [
        "UV_CACHE_DIR",
        "NPM_CONFIG_CACHE",
        "PNPM_HOME",
        "YARN_CACHE_FOLDER",
        "CARGO_HOME",
        "GOPATH",
        "GOCACHE",
        "GRADLE_USER_HOME",
        "M2_HOME",
        "NUGET_PACKAGES",
        "CCACHE_DIR",
        "DENO_DIR",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
    ]
    for env_var in cache_env_vars:
        val = os.environ.get(env_var)
        if val:
            roots.append(os.path.abspath(val))

    home = os.path.expanduser("~")
    if home and home != "~":
        # Standard XDG & system caches
        if not os.environ.get("XDG_CACHE_HOME"):
            roots.append(os.path.join(home, ".cache"))
        if not os.environ.get("XDG_DATA_HOME"):
            roots.append(os.path.join(home, ".local", "share"))
        if not os.environ.get("XDG_STATE_HOME"):
            roots.append(os.path.join(home, ".local", "state"))

        # Ecosystem-specific cache roots
        common_cache_dirs = [
            # JavaScript / TypeScript / Node / Bun / Deno
            os.path.join(home, ".npm"),
            os.path.join(home, ".pnpm-store"),
            os.path.join(home, ".yarn"),
            os.path.join(home, ".bun"),
            os.path.join(home, ".deno"),
            os.path.join(home, ".node-gyp"),
            os.path.join(home, ".nvm"),
            # Rust
            os.path.join(home, ".cargo", "registry"),
            os.path.join(home, ".cargo", "git"),
            os.path.join(home, ".rustup"),
            # Go
            os.path.join(home, "go"),
            # Python
            os.path.join(home, ".virtualenvs"),
            os.path.join(home, ".pyenv"),
            os.path.join(home, ".pipx"),
            # Java / Kotlin / Gradle / Maven / Android
            os.path.join(home, ".gradle"),
            os.path.join(home, ".m2", "repository"),
            os.path.join(home, ".ivy2"),
            os.path.join(home, ".sbt"),
            os.path.join(home, ".android"),
            # C / C++ / Zig
            os.path.join(home, ".ccache"),
            os.path.join(home, ".conan"),
            os.path.join(home, ".conan2"),
            os.path.join(home, ".vcpkg"),
            os.path.join(home, ".zig-cache"),
            # .NET
            os.path.join(home, ".nuget"),
            os.path.join(home, ".dotnet"),
            # Ruby / PHP
            os.path.join(home, ".bundle"),
            os.path.join(home, ".composer"),
        ]
        roots.extend(common_cache_dirs)

        if platform.system() == "Darwin":
            roots.append(os.path.join(home, "Library", "Caches"))

    # Return deduplicated list
    seen = set()
    deduped: List[str] = []
    for r in roots:
        norm = os.path.normpath(r)
        if norm not in seen:
            seen.add(norm)
            deduped.append(norm)
    return deduped


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
        sys_temp = tempfile.gettempdir()
        if sys_temp:
            raw_roots.append(sys_temp)
        raw_roots.extend(get_default_writable_cache_roots())
    else:
        win_temp = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
        if win_temp and not win_temp.startswith(("/tmp", "/private/tmp", "/dev")):
            raw_roots.append(win_temp)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            raw_roots.append(local_app_data)
        raw_roots.extend(get_default_writable_cache_roots())

    if allow_workspace_writes:
        raw_roots.append(workspace)
        raw_roots.extend(get_git_worktree_writable_roots(workspace))

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


_cached_resolved_default_deny: Optional[List[str]] = None


def _get_resolved_default_deny_clean() -> List[str]:
    global _cached_resolved_default_deny
    if _cached_resolved_default_deny is None:
        res = []
        for deny in get_default_deny_read_paths():
            deny_abs = os.path.abspath(deny)
            deny_real = os.path.realpath(deny_abs)
            for d in (deny_abs, deny_real):
                clean = os.path.normcase(d).rstrip(os.sep)
                if clean not in res:
                    res.append(clean)
        _cached_resolved_default_deny = res
    return _cached_resolved_default_deny


def is_path_readable_in_sandbox(
    path: str,
    cwd: Optional[str] = None,
    extra_deny_read_paths: Optional[List[str]] = None,
) -> bool:
    """Check if path is allowed for reading in sandbox mode (blocks sensitive paths)."""
    target_abs = os.path.realpath(os.path.abspath(path))
    target_norm = os.path.normcase(target_abs)
    clean_denies = _get_resolved_default_deny_clean()

    for clean_deny in clean_denies:
        if target_norm == clean_deny or target_norm.startswith(clean_deny + os.sep):
            return False

    if extra_deny_read_paths:
        for deny in extra_deny_read_paths:
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


_SEATBELT_PROFILE_CACHE: Dict[Tuple[str, Tuple[str, ...], Tuple[str, ...], bool, Optional[str]], str] = {}
_SEATBELT_PROFILE_CACHE_MAX = 128


def generate_seatbelt_profile(
    workspace_dir: str,
    extra_writable_roots: Optional[List[str]] = None,
    extra_deny_read_paths: Optional[List[str]] = None,
    allow_workspace_writes: bool = True,
    sys_temp: Optional[str] = None,
) -> str:
    """Generate macOS Seatbelt (SBPL) profile string allowing writes only in workspace, temp dirs, and /dev."""
    cache_key = (
        workspace_dir,
        tuple(extra_writable_roots or ()),
        tuple(extra_deny_read_paths or ()),
        allow_workspace_writes,
        sys_temp,
    )
    if cache_key in _SEATBELT_PROFILE_CACHE:
        return _SEATBELT_PROFILE_CACHE[cache_key]

    workspace_abs = os.path.abspath(workspace_dir)
    workspace_real = os.path.realpath(workspace_abs)

    writable_paths = [
        "/tmp",
        "/private/tmp",
        "/dev",
    ]
    if allow_workspace_writes:
        writable_paths.extend([workspace_abs, workspace_real])
        for wt_root in get_git_worktree_writable_roots(workspace_abs):
            for item in (os.path.abspath(wt_root), os.path.realpath(wt_root)):
                if item not in writable_paths and not _is_fs_root(os.path.normcase(item)):
                    writable_paths.append(item)

    sys_temp = sys_temp or tempfile.gettempdir()
    if sys_temp:
        for t in (os.path.abspath(sys_temp), os.path.realpath(sys_temp)):
            if t not in writable_paths and not _is_fs_root(os.path.normcase(os.path.realpath(t))):
                writable_paths.append(t)

    for c in get_default_writable_cache_roots():
        for item in (os.path.abspath(c), os.path.realpath(c)):
            if item not in writable_paths and not _is_fs_root(os.path.normcase(item)):
                writable_paths.append(item)

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

    profile = f"""(version 1)
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
    if len(_SEATBELT_PROFILE_CACHE) >= _SEATBELT_PROFILE_CACHE_MAX:
        _SEATBELT_PROFILE_CACHE.clear()
    _SEATBELT_PROFILE_CACHE[cache_key] = profile
    return profile


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
    if allow_workspace_writes:
        candidates.extend(get_git_worktree_writable_roots(workspace_abs))
    candidates.extend(get_default_writable_cache_roots())
    if extra_writable_roots:
        candidates.extend(extra_writable_roots)
    for extra in candidates:
        extra_abs = os.path.realpath(os.path.abspath(extra))
        if not exists(extra_abs):
            try:
                os.makedirs(extra_abs, exist_ok=True)
            except Exception:
                pass
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
    workspace_dir: Optional[str] = None,
) -> Tuple[str, List[str], bool]:
    """Wrap command with platform-specific sandbox if available.

    Returns:
        (executable, args_list, is_sandboxed)
    """
    workspace = workspace_dir or cwd or os.getcwd()
    workspace_abs = os.path.realpath(os.path.abspath(workspace))
    shell = shell_executable() or "/bin/sh"

    if platform.system() == "Darwin" and is_sandbox_supported():
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
