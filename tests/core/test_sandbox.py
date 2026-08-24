import os
from unittest.mock import patch

from core.infrastructure.platform.sandbox import (
    build_sandboxed_command,
    generate_seatbelt_profile,
    get_sandbox_backend_name,
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
    assert f'(require-not (subpath "{os.path.realpath(cwd)}"))' in profile
    assert '(require-not (subpath "/tmp"))' in profile
    assert '(require-not (subpath "/dev"))' in profile
    assert ".ssh" in profile
    assert ".aws" in profile
    assert "Keychains" in profile
    assert "config.json" in profile


def test_is_sandbox_supported():
    with patch("platform.system", return_value="Darwin"), patch("os.path.exists", return_value=True):
        assert is_sandbox_supported() is True
        assert get_sandbox_backend_name() == "seatbelt"

    with patch("platform.system", return_value="Linux"), patch("shutil.which", return_value="/usr/bin/bwrap"):
        assert is_sandbox_supported() is True
        assert get_sandbox_backend_name() == "bubblewrap"

    with patch("platform.system", return_value="Windows"):
        assert is_sandbox_supported() is False
        assert get_sandbox_backend_name() == "none"


def test_build_sandboxed_command_darwin():
    with patch("platform.system", return_value="Darwin"), patch("os.path.exists", return_value=True):
        exe, args, sandboxed = build_sandboxed_command("echo 1", cwd="/tmp/test_dir")
        assert exe == "/usr/bin/sandbox-exec"
        assert args[0] == "-p"
        assert sandboxed is True
        assert "echo 1" in args[-1]


def test_build_sandboxed_command_linux():
    with patch("platform.system", return_value="Linux"), patch("shutil.which", return_value="/usr/bin/bwrap"):
        exe, args, sandboxed = build_sandboxed_command("echo 1", cwd="/tmp/test_dir")
        assert exe == "/usr/bin/bwrap"
        assert "--ro-bind" in args
        assert sandboxed is True
        assert "echo 1" in args[-1]


def test_build_sandboxed_command_unsupported():
    with patch("platform.system", return_value="Windows"):
        exe, args, sandboxed = build_sandboxed_command("echo 1", cwd="/tmp/test_dir")
        assert sandboxed is False
        assert "echo 1" in args[-1]


def test_is_path_writable_in_sandbox():
    cwd = "/Users/test/workspace"
    assert is_path_writable_in_sandbox("/Users/test/workspace/file.txt", cwd=cwd) is True
    assert is_path_writable_in_sandbox("/tmp/file.txt", cwd=cwd) is True
    assert is_path_writable_in_sandbox("/Users/test/other_dir/file.txt", cwd=cwd) is False


def test_is_path_readable_in_sandbox():
    home = os.path.expanduser("~")
    assert is_path_readable_in_sandbox(os.path.join(home, ".ssh", "id_rsa")) is False
    assert is_path_readable_in_sandbox(os.path.join(home, ".aws", "credentials")) is False
    assert is_path_readable_in_sandbox(os.path.join(home, ".johnston", "config.json")) is False
    assert is_path_readable_in_sandbox(os.path.join(home, "Library", "Keychains", "login.keychain-db")) is False
    assert is_path_readable_in_sandbox("/Users/test/workspace/file.txt") is True
