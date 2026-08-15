"""Edge-case tests hunting for bugs in core/git_utils.py and config I/O.

Targets run_git / make_git_diff (core/git_utils.py) and the JSON config
read/write path (core.infrastructure.platform.platform_utils.read_json / atomic_write_json,
core.config_helpers.ensure_json_config, ProviderManager._read_config).
Does NOT duplicate tests/core/test_git_utils.py.
"""

import json
import os
import subprocess
from unittest.mock import patch

import pytest

from core.config_helpers import ensure_json_config
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json
from core.infrastructure.runtime.git_utils import make_git_diff, run_git
from core.provider_manager import ProviderManager


def make_repo(tmp_path):
    """Initializes a real git repo in tmp_path, returns the path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    return repo


# ---------------------------------------------------------------- run_git


def test_returns_124_timeout_when_git_hangs():
    """A hanging git must be turned into rc=124, never raise."""
    with patch(
        "core.infrastructure.runtime.git_utils.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["git", "fetch"], timeout=0.01),
    ):
        res = run_git(["fetch"], timeout=0.01)
    assert res.returncode == 124
    assert "timeout" in res.stderr


def test_timeout_none_passes_through_and_completes():
    """timeout=None must not raise and must reach subprocess."""
    with patch("core.infrastructure.runtime.git_utils.subprocess.run") as m:
        m.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        res = run_git(["rev-parse", "HEAD"])
    assert res.returncode == 0
    assert m.call_args.kwargs["timeout"] is None


def test_empty_args_passes_git_alone():
    """run_git([]) must invoke bare `git` (help screen), not crash."""
    with patch("core.infrastructure.runtime.git_utils.subprocess.run") as m:
        m.return_value = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="usage", stderr="")
        res = run_git([])
    assert res.returncode == 0
    assert m.call_args.args[0] == ["git"]


def test_none_arg_does_not_crash():
    """An int/None arg must not crash run_git (graceful rc=1)."""
    res = run_git([None])  # type: ignore[list-item]
    assert res.returncode == 1
    assert res.stderr


def test_nonstring_arg_does_not_crash():
    res = run_git([123])  # type: ignore[list-item]
    assert res.returncode == 1
    assert res.stderr


def test_unicode_args_invoked_as_literal_list():
    """Unicode args must be passed intact as a list element (no shell)."""
    with patch("core.infrastructure.runtime.git_utils.subprocess.run") as m:
        m.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        run_git(["log", "--format=%s", "мой-коммит 🎉"])
    assert m.call_args.args[0] == ["git", "log", "--format=%s", "мой-коммит 🎉"]
    assert m.call_args.kwargs.get("shell") is not True


def test_args_with_spaces_preserved_as_single_element():
    """Spaces in an arg must NOT be split — passed as one list element."""
    with patch("core.infrastructure.runtime.git_utils.subprocess.run") as m:
        m.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        run_git(["commit", "-m", "feat: hello world"])
    assert m.call_args.args[0] == ["git", "commit", "-m", "feat: hello world"]


def test_injection_metachars_not_executed_via_shell():
    """`; && | $(...)` in args must not execute as shell commands."""
    with patch("core.infrastructure.runtime.git_utils.subprocess.run") as m:
        m.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        run_git(["rev-parse", "HEAD; echo pwned"])
    assert m.call_args.args[0] == ["git", "rev-parse", "HEAD; echo pwned"]
    assert m.call_args.kwargs.get("shell") is None or m.call_args.kwargs.get("shell") is False


def test_injection_metachars_real_git_errors(tmp_path):
    """Real git: injected metachars must NOT execute as shell commands.

    run_git uses a list (no shell), so `; echo ...` must be treated as a
    literal arg. If it ran through a shell, the marker file would be created.
    """
    marker = tmp_path / "pwned"
    repo = make_repo(tmp_path)
    res = run_git(["rev-parse", f"HEAD; test -f {marker} && echo INJECTED"], cwd=str(repo))
    assert res.returncode != 0  # git errors on the literal ref, not shell success
    assert not marker.exists()


def test_nonzero_rc_stderr_parsed():
    """Non-zero rc must keep stderr, not crash."""
    with patch("core.infrastructure.runtime.git_utils.subprocess.run") as m:
        m.return_value = subprocess.CompletedProcess(
            args=["git", "x"], returncode=128, stdout="", stderr="fatal: unknown command"
        )
        res = run_git(["x"])
    assert res.returncode == 128
    assert res.stderr == "fatal: unknown command"


def test_env_none_vs_empty_dict_vs_git_dir_passthrough():
    with patch("core.infrastructure.runtime.git_utils.subprocess.run") as m:
        m.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        run_git(["status"])
        run_git(["status"], env={})
        run_git(["status"], env={"GIT_DIR": "/tmp/x"})
    kwargs_s = [c.kwargs["env"] for c in m.call_args_list]
    assert kwargs_s[0] is None
    assert kwargs_s[1] == {}
    assert kwargs_s[2] == {"GIT_DIR": "/tmp/x"}


def test_large_stdout_returned_in_full():
    """A very large stdout must be returned un-truncated by run_git."""
    big = "x" * (2_000_000)
    with patch("core.infrastructure.runtime.git_utils.subprocess.run") as m:
        m.return_value = subprocess.CompletedProcess(args=["git", "log"], returncode=0, stdout=big, stderr="")
        res = run_git(["log"])
    assert len(res.stdout) == len(big)


def test_binary_bytes_stdout_handled():
    """run_git uses text=True so subprocess decodes bytes to str.

    Feed str output (as CompletedProcess returns after text=True decoding);
    ensure run_git likewise returns str and doesn't crash.
    """
    with patch("core.infrastructure.runtime.git_utils.subprocess.run") as m:
        m.return_value = subprocess.CompletedProcess(
            args=["git", "cat-file"], returncode=0, stdout="\ufffd\ufffd\ufffd garbage", stderr=""
        )
        res = run_git(["cat-file"])
    assert isinstance(res.stdout, str)


def test_git_missing_in_path_returns_1():
    with patch("core.infrastructure.runtime.git_utils.subprocess.run", side_effect=FileNotFoundError("No such file: git")):
        res = run_git(["status"])
    assert res.returncode == 1
    assert "git" in res.stderr


def test_cwd_not_a_git_repo_real(tmp_path):
    res = run_git(["rev-parse", "HEAD"], cwd=str(tmp_path))
    assert res.returncode != 0  # not a repo -> git errors, no crash


def test_make_git_diff_unicode_real(tmp_path):
    d = make_git_diff("héllo wörld\n", "héllo wörld 🎉\n", fromfile="a.py", tofile="b.py")
    assert "héllo wörld" in d
    assert "🎉" in d


def test_make_git_diff_identical_unicode_returns_empty():
    assert make_git_diff("héllo 🎉\n", "héllo 🎉\n") == ""


# ---------------------------------------------------------------- config I/O


def test_read_json_missing_returns_default(tmp_path):
    p = tmp_path / "nope.json"
    assert read_json(str(p), {"d": 1}) == {"d": 1}
    assert read_json(str(p)) is None


def test_read_json_broken_json_returns_default(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert read_json(str(p), []) == []


def test_read_json_empty_file_returns_default(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("", encoding="utf-8")
    assert read_json(str(p), "fallback") == "fallback"


def test_read_json_only_comments_returns_default(tmp_path):
    p = tmp_path / "comments.json"
    p.write_text("// just a comment\n/* block */", encoding="utf-8")
    assert read_json(str(p), {"x": 1}) == {"x": 1}


def test_read_json_unicode_and_nested_roundtrip(tmp_path):
    p = tmp_path / "uni.json"
    data = {"ключ": "значение 🎉", "nested": {"a": [1, 2, {"b": None}]}}
    atomic_write_json(str(p), data)
    assert read_json(str(p)) == data


def test_read_json_does_not_mutate_source(tmp_path):
    p = tmp_path / "cfg.json"
    atomic_write_json(str(p), {"k": "v"})
    before = json.loads(p.read_text(encoding="utf-8"))
    read_json(str(p))
    assert json.loads(p.read_text(encoding="utf-8")) == before


def test_read_json_repeated_reads_stable(tmp_path):
    p = tmp_path / "cfg.json"
    atomic_write_json(str(p), {"k": "v"})
    assert read_json(str(p)) == read_json(str(p)) == {"k": "v"}


def test_read_json_top_level_list_preserved(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1,2,3]", encoding="utf-8")
    assert read_json(str(p)) == [1, 2, 3]


def test_read_json_top_level_scalar_preserved(tmp_path):
    p = tmp_path / "scalar.json"
    p.write_text('"hello"', encoding="utf-8")
    assert read_json(str(p)) == "hello"


def test_atomic_write_json_creates_parent_dir(tmp_path):
    target = tmp_path / "a" / "b" / "c.json"
    atomic_write_json(str(target), {"x": 1})
    assert target.exists()
    assert read_json(str(target)) == {"x": 1}


def test_atomic_write_json_unicode_ensure_ascii_false(tmp_path):
    target = tmp_path / "u.json"
    atomic_write_json(str(target), {"t": "текст 🎉"})
    content = target.read_text(encoding="utf-8")
    assert "текст" in content and "🎉" in content


def test_atomic_write_json_to_readonly_dir_fails(tmp_path):
    """Writing into a read-only directory must raise, not silently lose data."""
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o555)
    try:
        with pytest.raises(Exception):
            atomic_write_json(str(ro / "cfg.json"), {"x": 1})
    finally:
        os.chmod(ro, 0o755)


def test_atomic_write_json_write_to_nonexistent_nested_readonly_dir(tmp_path):
    """Non-existent parent under a read-only dir must raise, not silently lose data."""
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o555)
    try:
        with pytest.raises(Exception):
            ensure_json_config(str(ro / "sub" / "cfg.json"), {"k": "v"})
    finally:
        os.chmod(ro, 0o755)


def test_read_json_binary_garbage_returns_default(tmp_path):
    p = tmp_path / "bin.json"
    p.write_bytes(b"\xff\xfe\x00\x01\x02")
    assert read_json(str(p), {"d": 1}) == {"d": 1}


def test_provider_manager_read_config_non_dict_returns_empty(tmp_path):
    """A config file holding a non-dict (e.g. a list) must not poison the manager."""
    with patch("core.provider_manager.CONFIG_FILE", str(tmp_path / "cfg.json")):
        with patch("core.provider_manager.PROVIDERS_JSON_FILE", str(tmp_path / "prov.json")):
            cfg = tmp_path / "cfg.json"
            cfg.write_text("[1,2,3]", encoding="utf-8")
            pm = ProviderManager()
            assert pm._read_config() == {}
            assert pm._get_config_data() == {}


def test_provider_manager_broken_config_file_returns_empty(tmp_path):
    with patch("core.provider_manager.CONFIG_FILE", str(tmp_path / "cfg.json")):
        with patch("core.provider_manager.PROVIDERS_JSON_FILE", str(tmp_path / "prov.json")):
            cfg = tmp_path / "cfg.json"
            cfg.write_text("{broken", encoding="utf-8")
            pm = ProviderManager()
            assert pm._read_config() == {}


def test_provider_manager_missing_config_returns_empty(tmp_path):
    with patch("core.provider_manager.CONFIG_FILE", str(tmp_path / "absent.json")):
        with patch("core.provider_manager.PROVIDERS_JSON_FILE", str(tmp_path / "prov.json")):
            pm = ProviderManager()
            assert pm._read_config() == {}
            assert pm._get_config_data() == {}


def test_provider_manager_nested_missing_key_no_keyerror(tmp_path):
    """Absent nested key via .get() chains must not raise KeyError."""
    with patch("core.provider_manager.CONFIG_FILE", str(tmp_path / "cfg.json")):
        with patch("core.provider_manager.PROVIDERS_JSON_FILE", str(tmp_path / "prov.json")):
            cfg = tmp_path / "cfg.json"
            cfg.write_text('{"api_keys": {}}', encoding="utf-8")
            pm = ProviderManager()
            assert pm.get_api_key("nope") == ""


def test_ensure_json_config_does_not_overwrite_existing(tmp_path):
    target = tmp_path / "cfg.json"
    target.write_text('{"exists": true}', encoding="utf-8")
    ensure_json_config(str(target), {"default": 1})
    assert read_json(str(target)) == {"exists": True}


def test_ensure_json_config_creates_missing_with_default(tmp_path):
    target = tmp_path / "sub" / "cfg.json"
    ensure_json_config(str(target), {"d": "v"})
    assert read_json(str(target)) == {"d": "v"}
