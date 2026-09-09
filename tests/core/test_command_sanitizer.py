"""Unit tests for core/infrastructure/platform/command_sanitizer.py."""

import tempfile

from johnston.core.infrastructure.platform.command_sanitizer import (
    _ENV_VAR_RE,
    _PREFIX_WRAPPERS,
    _REDUNDANT_CD_PATTERN,
    _STANDALONE_CD_PATTERN,
    _WRAPPER_OPTS_WITH_ARG,
    clean_cd_command,
    clean_command_wrappers,
)


def test_command_sanitizer_constants():
    assert _REDUNDANT_CD_PATTERN is not None
    assert _STANDALONE_CD_PATTERN is not None
    assert _ENV_VAR_RE.match("FOO=1")
    assert _ENV_VAR_RE.match("_BAR=val")
    assert not _ENV_VAR_RE.match("1FOO=1")
    assert "sudo" in _PREFIX_WRAPPERS
    assert "env" in _PREFIX_WRAPPERS
    assert "-u" in _WRAPPER_OPTS_WITH_ARG
    assert "--user" in _WRAPPER_OPTS_WITH_ARG


def test_clean_cd_command_redundant_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        cleaned, err = clean_cd_command(f"cd {tmpdir} && ls -la", tmpdir)
        assert err is None
        assert cleaned == "ls -la"

        cleaned, err = clean_cd_command(f'cd "{tmpdir}" ; echo hi', tmpdir)
        assert err is None
        assert cleaned == "echo hi"


def test_clean_cd_command_dot():
    cleaned, err = clean_cd_command("cd . && ls", "/some/path")
    assert err is None
    assert cleaned == "ls"

    cleaned, err = clean_cd_command("cd .\\ && ls", "/some/path")
    assert err is None
    assert cleaned == "ls"


def test_clean_cd_command_standalone_rejected():
    cleaned, err = clean_cd_command("cd /other/path", "/some/path")
    assert err is not None
    assert "Directory changes via 'cd' do not persist" in err

    cleaned, err = clean_cd_command("cd", "/some/path")
    assert err is not None
    assert "Directory changes via 'cd' do not persist" in err


def test_clean_cd_command_standalone_dot_allowed():
    cleaned, err = clean_cd_command("cd .", "/some/path")
    assert err is None
    assert cleaned == "cd ."

    cleaned, err = clean_cd_command("cd .\\", "/some/path")
    assert err is None
    assert cleaned == "cd .\\"


def test_clean_command_wrappers_empty():
    assert clean_command_wrappers("") == ""
    assert clean_command_wrappers("   ") == ""
    assert clean_command_wrappers(None) == ""


def test_clean_command_wrappers_no_wrappers():
    assert clean_command_wrappers("git status") == "git status"
    assert clean_command_wrappers("echo 'hello world'") == "echo 'hello world'"
    assert clean_command_wrappers("pytest -m slow") == "pytest -m slow"


def test_clean_command_wrappers_simple_wrappers():
    assert clean_command_wrappers("sudo git commit -m 'test'") == "git commit -m 'test'"
    assert clean_command_wrappers("sudo -u root git status") == "git status"
    assert clean_command_wrappers("sudo -E git status") == "git status"
    assert clean_command_wrappers("sudo -- git status") == "git status"
    assert clean_command_wrappers("env VAR=1 git status") == "git status"
    assert clean_command_wrappers("nice -n 10 git status") == "git status"
    assert clean_command_wrappers("time python app.py") == "python app.py"
    assert clean_command_wrappers("exec pytest") == "pytest"
    assert clean_command_wrappers("nohup python app.py") == "python app.py"


def test_clean_command_wrappers_nested_wrappers():
    assert (
        clean_command_wrappers("sudo env FOO=bar nice -n 5 time git diff")
        == "git diff"
    )


def test_clean_command_wrappers_env_assignments():
    assert clean_command_wrappers("FOO=1 BAR=2 git diff") == "git diff"


def test_clean_command_wrappers_compound_commands():
    assert (
        clean_command_wrappers("true && sudo git commit -m 'msg'")
        == "true && git commit -m 'msg'"
    )
    assert (
        clean_command_wrappers("echo hi | sudo -E git push origin main")
        == "echo hi | git push origin main"
    )
    assert (
        clean_command_wrappers("sudo git status ; sudo git diff")
        == "git status ; git diff"
    )


def test_clean_command_wrappers_standalone_wrapper():
    assert clean_command_wrappers("sudo") == ""
    assert clean_command_wrappers("sudo -u root") == ""


def test_clean_command_wrappers_quotes_with_operators():
    # Quotes containing semicolons or ampersands must not be split
    cmd = 'sudo git commit -m "feat; fix bug && something"'
    cleaned = clean_command_wrappers(cmd)
    assert "git commit" in cleaned
    assert "feat; fix bug && something" in cleaned


def test_strip_wrapper_tokens():
    from johnston.core.infrastructure.platform.command_sanitizer import strip_wrapper_tokens

    assert strip_wrapper_tokens(["sudo", "git", "commit"]) == ["git", "commit"]
    assert strip_wrapper_tokens(["env", "A=1", "nice", "-n", "5", "ls"]) == ["ls"]
    assert strip_wrapper_tokens(["VAR=val", "python"]) == ["python"]
    assert strip_wrapper_tokens(["ls", "-la"]) == ["ls", "-la"]

