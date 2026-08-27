import os
import subprocess
from unittest.mock import patch

from core.infrastructure.platform.sandbox import (
    _build_bwrap_args,
    _escape_sbpl_path,
    build_sandboxed_command,
    generate_seatbelt_profile,
    is_path_readable_in_sandbox,
    is_path_writable_in_sandbox,
    is_sandbox_supported,
)


def test_generate_seatbelt_profile():
    cwd = os.path.abspath("/Users/test/my_project")
    profile = generate_seatbelt_profile(cwd, extra_writable_roots=["/var/extra"])
    assert "(version 1)" in profile
    assert "(allow default)" in profile
    assert "(deny file-write*" in profile
    assert f'(require-not (subpath "{_escape_sbpl_path(os.path.realpath(cwd))}"))' in profile
    assert ".ssh" in profile
    assert ".aws" in profile
    assert ".gnupg" in profile


def test_generate_seatbelt_profile_ignores_fs_root_extra():
    """extra_writable_roots=['/'] must NOT neutralize the deny-write rule."""
    cwd = os.path.abspath("/Users/test/my_project")
    profile = generate_seatbelt_profile(cwd, extra_writable_roots=["/"])
    assert '(require-not (subpath "/"))' not in profile


def test_is_sandbox_supported():
    with (
        patch("platform.system", return_value="Darwin"),
        patch("os.path.exists", return_value=True),
        patch("core.infrastructure.platform.sandbox._check_seatbelt", return_value=True),
    ):
        assert is_sandbox_supported() is True

    with (
        patch("platform.system", return_value="Linux"),
        patch("shutil.which", return_value="/usr/bin/bwrap"),
        patch("core.infrastructure.platform.sandbox._check_bwrap", return_value=True),
    ):
        assert is_sandbox_supported() is True

    with patch("platform.system", return_value="Windows"):
        assert is_sandbox_supported() is True

    with patch("platform.system", return_value="FreeBSD"):
        assert is_sandbox_supported() is False


def test_build_sandboxed_command_darwin():
    with (
        patch("platform.system", return_value="Darwin"),
        patch("os.path.exists", return_value=True),
        patch("core.infrastructure.platform.sandbox._check_seatbelt", return_value=True),
    ):
        exe, args, sandboxed = build_sandboxed_command("echo 1", cwd="/tmp/test_dir")
        assert exe == "/usr/bin/sandbox-exec"
        assert args[0] == "-p"
        assert sandboxed is True
        assert "echo 1" in args[-1]


def test_build_sandboxed_command_linux():
    with (
        patch("platform.system", return_value="Linux"),
        patch("shutil.which", return_value="/usr/bin/bwrap"),
        patch("core.infrastructure.platform.sandbox._check_bwrap", return_value=True),
    ):
        exe, args, sandboxed = build_sandboxed_command("echo 1", cwd="/tmp/test_dir")
        assert exe == "/usr/bin/bwrap"
        assert "--ro-bind" in args
        assert sandboxed is True
        assert "echo 1" in args[-1]


def test_build_sandboxed_command_linux_bwrap_unusable_falls_back():
    """bwrap present but namespaces blocked -> unsandboxed fallback (surfaced upstream)."""
    with (
        patch("platform.system", return_value="Linux"),
        patch("shutil.which", return_value="/usr/bin/bwrap"),
        patch("core.infrastructure.platform.sandbox._check_bwrap", return_value=False),
    ):
        exe, args, sandboxed = build_sandboxed_command("echo 1", cwd="/tmp/test_dir")
        assert sandboxed is False


def test_check_bwrap_probes_once_and_caches(tmp_path):
    import core.infrastructure.platform.sandbox as sbx

    sbx._bwrap_probe_cache.clear()
    fake = str(tmp_path / "bwrap")
    with patch.object(sbx.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as mock_run:
        assert sbx._check_bwrap(fake) is True
        assert sbx._check_bwrap(fake) is True
        assert mock_run.call_count == 1
        # Smoke-test must execute a real binary inside a namespace.
        assert mock_run.call_args.args[0][:2] == [fake, "--ro-bind"]
        assert mock_run.call_args.args[0][-1] == "/bin/true"

    sbx._bwrap_probe_cache.clear()
    with patch.object(sbx.subprocess, "run", side_effect=OSError("boom")):
        assert sbx._check_bwrap(fake) is False


def test_build_sandboxed_command_windows():
    with patch("platform.system", return_value="Windows"):
        exe, args, sandboxed = build_sandboxed_command("echo 1", cwd="C:\\test_dir")
        assert sandboxed is True
        # Must be launched by absolute script path (not -m: child cwd is the workspace).
        assert args[0].endswith("win_sandbox_runner.py")
        assert os.path.isabs(args[0])
        assert "--command" in args
        assert "echo 1" in args


def test_build_sandboxed_command_unsupported(caplog):
    with patch("platform.system", return_value="FreeBSD"):
        exe, args, sandboxed = build_sandboxed_command("echo 1", cwd="/tmp/test_dir")
        assert sandboxed is False
        assert "echo 1" in args[-1]
    assert any("unsupported" in r.message for r in caplog.records)


def test_is_path_writable_in_sandbox():
    with patch("platform.system", return_value="Darwin"):
        cwd = "/Users/test/workspace"
        assert is_path_writable_in_sandbox("/Users/test/workspace/file.txt", cwd=cwd) is True
        assert is_path_writable_in_sandbox("/Users/test/workspace/file.txt", cwd=cwd, allow_workspace_writes=False) is False
        assert is_path_writable_in_sandbox("/tmp/file.txt", cwd=cwd) is True
        assert is_path_writable_in_sandbox("/tmp/file.txt", cwd=cwd, allow_workspace_writes=False) is True
        assert is_path_writable_in_sandbox("/Users/test/other_dir/file.txt", cwd=cwd) is False


def test_is_path_writable_fs_root_extra_grants_nothing():
    """Regression: fs-root extra root used to fall through and grant ALL writes."""
    cwd = "/Users/test/workspace"
    assert is_path_writable_in_sandbox("/etc/hosts", cwd=cwd, extra_writable_roots=["/"]) is False
    assert is_path_writable_in_sandbox("/home/x/f", cwd=cwd, extra_writable_roots=["/"]) is False
    # Workspace itself still writable.
    assert is_path_writable_in_sandbox(f"{cwd}/f", cwd=cwd, extra_writable_roots=["/"]) is True


def test_is_path_writable_workspace_is_root(monkeypatch):
    monkeypatch.chdir("/")
    assert is_path_writable_in_sandbox("/etc/hosts", cwd="/") is True


def test_is_path_writable_posix_tmp_not_granted_on_windows():
    """POSIX-only tmp roots must not leak into the Windows writable set."""
    with patch("platform.system", return_value="Windows"):
        assert is_path_writable_in_sandbox("/tmp/file.txt", cwd="/Users/test/ws") is False
        assert is_path_writable_in_sandbox("/dev/null", cwd="/Users/test/ws") is False


def test_build_bwrap_args_skips_root_extra_and_binds_sys_temp():
    custom_tmp = os.path.realpath(os.path.abspath("/custom/tmp"))
    var_tmp = os.path.realpath(os.path.abspath("/var/tmp"))
    args = _build_bwrap_args(
        "/ws",
        extra_writable_roots=["/"],
        sys_temp="/custom/tmp",
        exists=lambda p: p in (var_tmp, custom_tmp, "/var/tmp", "/custom/tmp"),
    )
    assert ["--bind", "/", "/"] not in [args[i : i + 3] for i in range(len(args))]
    assert ["--bind", custom_tmp, custom_tmp] in [args[i : i + 3] for i in range(len(args))]
    assert ["--bind", "/var/tmp", "/var/tmp"] in [args[i : i + 3] for i in range(len(args))]


def test_build_bwrap_args_dedupes_nested_sys_temp():
    """sys_temp inside /tmp or workspace must not be bound twice."""
    args = _build_bwrap_args("/ws", sys_temp="/tmp/deep/tmp", exists=lambda p: True)
    triples = [args[i : i + 3] for i in range(len(args))]
    bound = [t[1:] for t in triples if t[0] == "--bind"]
    assert ["/tmp", "/tmp"] in bound
    assert not any(b[1] == "/tmp/deep/tmp" for b in bound)


def test_build_bwrap_args_read_only_workspace():
    args = _build_bwrap_args("/ws", allow_workspace_writes=False, exists=lambda p: False)
    assert "--ro-bind" in args
    assert args[args.index("--ro-bind") + 1] == "/"


def test_build_bwrap_args_deny_reads():
    sensitive = os.path.realpath(os.path.abspath("/sensitive/file"))

    def exists(p):
        return p == sensitive or p.endswith("dir") or p.endswith("file")

    with patch("os.path.isdir", return_value=False), patch("os.path.isfile", return_value=True):
        args = _build_bwrap_args("/ws", deny_reads=["/sensitive/file"], exists=exists)
    assert ["--ro-bind", "/dev/null", sensitive] in [args[i : i + 3] for i in range(len(args))]


def test_generate_seatbelt_profile_read_only():
    cwd = os.path.abspath("/Users/test/my_project")
    profile = generate_seatbelt_profile(cwd, allow_workspace_writes=False)
    assert _escape_sbpl_path(os.path.realpath(cwd)) not in profile
    assert "/tmp" in profile


def test_build_sandboxed_command_read_only_darwin():
    with (
        patch("platform.system", return_value="Darwin"),
        patch("os.path.exists", return_value=True),
        patch("core.infrastructure.platform.sandbox._check_seatbelt", return_value=True),
    ):
        exe, args, sandboxed = build_sandboxed_command("echo 1", cwd="/tmp/test_dir", allow_workspace_writes=False)
        assert sandboxed is True
        profile = args[1]
        assert "/tmp" in profile


def test_build_sandboxed_command_read_only_linux():
    with (
        patch("platform.system", return_value="Linux"),
        patch("shutil.which", return_value="/usr/bin/bwrap"),
        patch("core.infrastructure.platform.sandbox._check_bwrap", return_value=True),
    ):
        exe, args, sandboxed = build_sandboxed_command("echo 1", cwd="/tmp/test_dir", allow_workspace_writes=False)
        assert sandboxed is True
        assert "--ro-bind" in args


def test_is_path_readable_in_sandbox():
    home = os.path.expanduser("~")
    assert is_path_readable_in_sandbox(os.path.join(home, ".ssh", "id_rsa")) is False
    assert is_path_readable_in_sandbox(os.path.join(home, ".aws", "credentials")) is False
    assert is_path_readable_in_sandbox(os.path.join(home, ".gnupg", "secring.gpg")) is False
    assert is_path_readable_in_sandbox("/Users/test/workspace/file.txt") is True


def test_load_and_save_sandbox_config(tmp_path):
    from core.infrastructure.config.config_helpers import load_sandbox_config, save_sandbox_config

    cfg_file = str(tmp_path / "config.json")
    assert load_sandbox_config(cfg_file) is False

    save_sandbox_config(True, config_file=cfg_file)
    assert load_sandbox_config(cfg_file) is True

    save_sandbox_config(False, config_file=cfg_file)
    assert load_sandbox_config(cfg_file) is False


def test_get_git_worktree_writable_roots(tmp_path):
    import core.infrastructure.platform.sandbox as sbx

    # Non-worktree: returns empty
    non_wt = tmp_path / "plain_dir"
    non_wt.mkdir()
    assert sbx.get_git_worktree_writable_roots(str(non_wt)) == []

    # Worktree with .git file pointing to valid gitdir and commondir
    main_git = tmp_path / "main_repo" / ".git"
    main_git.mkdir(parents=True)
    (main_git / "objects").mkdir()
    wt_gitdir = main_git / "worktrees" / "subagent-123"
    wt_gitdir.mkdir(parents=True)
    (wt_gitdir / "HEAD").write_text("ref: refs/heads/test\n", encoding="utf-8")
    (wt_gitdir / "commondir").write_text("../..\n", encoding="utf-8")

    wt_dir = tmp_path / "worktrees" / "subagent-123"
    wt_dir.mkdir(parents=True)
    (wt_dir / ".git").write_text(f"gitdir: {wt_gitdir}\n", encoding="utf-8")

    roots = sbx.get_git_worktree_writable_roots(str(wt_dir))
    assert os.path.realpath(str(wt_gitdir)) in roots
    assert os.path.realpath(str(main_git)) in roots

    # Forged .git pointing to sensitive dir (e.g. .ssh) -> rejected
    home_ssh = os.path.expanduser("~/.ssh")
    (wt_dir / ".git").write_text(f"gitdir: {home_ssh}\n", encoding="utf-8")
    assert sbx.get_git_worktree_writable_roots(str(wt_dir)) == []



def test_get_default_writable_cache_roots(monkeypatch):
    import core.infrastructure.platform.sandbox as sbx

    monkeypatch.setenv("UV_CACHE_DIR", "/custom/uv/cache")
    monkeypatch.setenv("XDG_CACHE_HOME", "/custom/xdg/cache")
    monkeypatch.setenv("NPM_CONFIG_CACHE", "/custom/npm/cache")
    monkeypatch.setenv("CARGO_HOME", "/custom/cargo/home")

    roots = sbx.get_default_writable_cache_roots()
    assert os.path.abspath("/custom/uv/cache") in roots
    assert os.path.abspath("/custom/xdg/cache") in roots
    assert os.path.abspath("/custom/npm/cache") in roots
    assert os.path.abspath("/custom/cargo/home") in roots

    # Test default home dirs when envs are cleared
    monkeypatch.delenv("NPM_CONFIG_CACHE", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    roots_default = sbx.get_default_writable_cache_roots()
    home = os.path.expanduser("~")
    assert os.path.join(home, ".npm") in roots_default
    assert os.path.join(home, ".cargo", "registry") in roots_default
    assert os.path.join(home, ".gradle") in roots_default


def test_check_seatbelt_probes_and_caches(tmp_path):
    import core.infrastructure.platform.sandbox as sbx

    sbx._seatbelt_probe_cache.clear()
    fake_exe = str(tmp_path / "sandbox-exec")
    (tmp_path / "sandbox-exec").write_text("#!/bin/sh\nexit 0\n")

    with patch.object(sbx.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as mock_run:
        assert sbx._check_seatbelt(fake_exe) is True
        assert sbx._check_seatbelt(fake_exe) is True
        assert mock_run.call_count == 1

    sbx._seatbelt_probe_cache.clear()
    with patch.object(sbx.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
        assert sbx._check_seatbelt(fake_exe) is False


def test_is_path_writable_in_sandbox_worktree_and_cache(tmp_path, monkeypatch):
    main_git = tmp_path / "repo" / ".git"
    main_git.mkdir(parents=True)
    wt_gitdir = main_git / "worktrees" / "wt1"
    wt_gitdir.mkdir(parents=True)
    (wt_gitdir / "commondir").write_text("../..\n", encoding="utf-8")

    wt_dir = tmp_path / "wt1"
    wt_dir.mkdir()
    (wt_dir / ".git").write_text(f"gitdir: {wt_gitdir}\n", encoding="utf-8")

    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv_cache"))

    # Worktree gitdir and commondir should be writable
    assert is_path_writable_in_sandbox(str(wt_gitdir / "index.lock"), cwd=str(wt_dir)) is True
    assert is_path_writable_in_sandbox(str(main_git / "objects" / "abc"), cwd=str(wt_dir)) is True
    # UV Cache should be writable
    assert is_path_writable_in_sandbox(str(tmp_path / "uv_cache" / "data"), cwd=str(wt_dir)) is True
    # Unrelated path outside is not writable
    assert is_path_writable_in_sandbox("/opt/unrelated/other/file", cwd=str(wt_dir)) is False

