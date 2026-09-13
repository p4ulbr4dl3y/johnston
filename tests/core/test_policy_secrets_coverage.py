"""Coverage-focused unit tests for ``johnston.core.domain.policies.policy_secrets``.

Exercises path resolution, shell-command token scanning, ``cd`` tracking and
error/edge branches not covered by the integration-level tests in
``tests/core/test_workspace_policy.py``.
"""

import os
import threading
from unittest.mock import patch

from johnston.core.domain.policies import permission_policy as _pp
from johnston.core.domain.policies.policy_secrets import (
    get_secrets_file,
    get_secrets_files,
    get_trusted_read_roots,
    is_secrets_file,
    is_secrets_shell_command,
)

_DEFAULT_LOGS = os.path.expanduser("~/.johnston/logs")
_DEFAULT_SECRETS = os.path.expanduser("~/.johnston/secrets.json")


class _FakePaths:
    def __init__(self, logs_dir=None, secrets_file=None):
        self.LOGS_DIR = logs_dir
        self.SECRETS_FILE = secrets_file


# --- get_trusted_read_roots -----------------------------------------------


def test_get_trusted_read_roots_with_paths_logs_dir(monkeypatch, tmp_path):
    config = str(tmp_path / "cfg")
    monkeypatch.setattr(
        "johnston.core.infrastructure.platform.paths",
        _FakePaths(logs_dir=os.path.join(config, "logs")),
    )
    monkeypatch.setattr(_pp, "LOGS_DIR", os.path.join(config, "other_logs"))

    roots = get_trusted_read_roots()
    assert roots == [
        os.path.join(config, "logs"),
        os.path.join(config, "other_logs"),
        _DEFAULT_LOGS,
    ]


def test_get_trusted_read_roots_without_paths_logs_dir(monkeypatch):
    monkeypatch.setattr(
        "johnston.core.infrastructure.platform.paths", _FakePaths(logs_dir=None)
    )
    monkeypatch.setattr(_pp, "LOGS_DIR", "")
    assert get_trusted_read_roots() == [_DEFAULT_LOGS]


def test_get_trusted_read_roots_paths_import_error(monkeypatch):
    monkeypatch.setattr(_pp, "LOGS_DIR", "")
    with patch("builtins.__import__", side_effect=ImportError("no platform.paths")):
        assert get_trusted_read_roots() == [_DEFAULT_LOGS]


# --- get_secrets_files / get_secrets_file ---------------------------------


def test_get_secrets_files_candidates(monkeypatch, tmp_path):
    config = str(tmp_path / "cfg")
    a = os.path.join(config, "a.json")
    b = os.path.join(config, "b.json")
    monkeypatch.setattr(
        "johnston.core.infrastructure.platform.paths", _FakePaths(secrets_file=a)
    )
    monkeypatch.setattr(_pp, "SECRETS_FILE", b)

    assert get_secrets_files() == [a, b, _DEFAULT_SECRETS]
    assert get_secrets_file() == a


def test_get_secrets_files_without_paths_secrets_file(monkeypatch):
    monkeypatch.setattr(
        "johnston.core.infrastructure.platform.paths",
        _FakePaths(secrets_file=None),
    )
    monkeypatch.setattr(_pp, "SECRETS_FILE", "")
    assert get_secrets_files() == [_DEFAULT_SECRETS]
    assert get_secrets_file() == _DEFAULT_SECRETS


def test_get_secrets_files_import_error(monkeypatch):
    monkeypatch.setattr(_pp, "SECRETS_FILE", "")
    with patch("builtins.__import__", side_effect=ImportError("no platform.paths")):
        assert get_secrets_files() == [_DEFAULT_SECRETS]


def test_get_secrets_file_empty_candidates_returns_pp_value(monkeypatch):
    monkeypatch.setattr(_pp, "SECRETS_FILE", "/fallback/secrets.json")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[],
    ):
        assert get_secrets_file() == "/fallback/secrets.json"


# --- is_secrets_file ------------------------------------------------------


def test_is_secrets_file_invalid_inputs():
    assert is_secrets_file("") is False
    assert is_secrets_file(None) is False
    assert is_secrets_file("   ") is False
    assert is_secrets_file(123) is False


def test_is_secrets_file_explicit_secrets_file_argument(tmp_path):
    sec = str(tmp_path / "cfg" / "secrets.json")
    assert is_secrets_file(sec, secrets_file=sec) is True
    assert is_secrets_file(str(tmp_path / "other.json"), secrets_file=sec) is False


def test_is_secrets_file_target_realpath_error(tmp_path):
    sec = str(tmp_path / "secrets.json")
    with patch("os.path.realpath", side_effect=OSError("gone")):
        assert is_secrets_file(sec, secrets_file=sec) is False


def test_is_secrets_file_candidate_realpath_error(tmp_path):
    """Candidate normalization failure falls back to the expanduser form."""
    sec = str(tmp_path / "cfg" / "secrets.json")
    orig_real = os.path.realpath

    def _fake_realpath(p):
        if p == os.path.abspath(os.path.expanduser(sec)):
            raise OSError("gone")
        return orig_real(p)

    with patch("os.path.realpath", side_effect=_fake_realpath):
        assert is_secrets_file(str(tmp_path / "other.json"), secrets_file=sec) is False


def test_is_secrets_file_cwd_dirname_match(tmp_path, monkeypatch):
    sec = str(tmp_path / "secrets.json")
    monkeypatch.chdir(str(tmp_path))
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        assert is_secrets_file("secrets.json") is True


def test_is_secrets_file_cwd_dirname_match_via_alias_file(tmp_path, monkeypatch):
    """Candidate in a different file name but same dir as cwd (line 108)."""
    (tmp_path / "sens.json").write_text("{}")
    monkeypatch.chdir(str(tmp_path))
    assert (
        is_secrets_file(
            "secrets.json", secrets_file=str(tmp_path / "sens.json")
        )
        is True
    )


def test_is_secrets_file_cwd_dirname_mismatch(tmp_path, monkeypatch):
    (tmp_path / "other").mkdir()
    sec = str(tmp_path / "cfg" / "secrets.json")
    monkeypatch.chdir(str(tmp_path / "other"))
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        assert is_secrets_file("secrets.json") is False


def test_is_secrets_file_samefile_match(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    os.symlink(str(real), str(link))
    assert is_secrets_file(str(link), secrets_file=str(real)) is True


def test_is_secrets_file_samefile_exception_suppressed(tmp_path):
    real = tmp_path / "a.json"
    real.write_text("{}")
    other = tmp_path / "b.json"
    other.write_text("{}")
    with patch("os.path.samefile", side_effect=OSError("cross-device")):
        assert is_secrets_file(str(other), secrets_file=str(real)) is False


def test_is_secrets_file_constant_shortcut(tmp_path):
    """Literal '.johnston/secrets.json' path hits the early-return (line 89)."""
    assert is_secrets_file(".johnston/secrets.json") is True
    assert is_secrets_file("~/.config/johnston/secrets.json") is True


def test_is_secrets_file_empty_candidate_skipped(tmp_path):
    candidate = str(tmp_path / "secrets.json")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=["", candidate],
    ):
        assert is_secrets_file(candidate) is True
        assert is_secrets_file(str(tmp_path / "other.txt")) is False


# --- is_secrets_shell_command ---------------------------------------------


def test_is_secrets_shell_command_invalid_inputs():
    assert is_secrets_shell_command("") is False
    assert is_secrets_shell_command(None) is False
    assert is_secrets_shell_command("   ") is False
    assert is_secrets_shell_command(123) is False


def test_is_secrets_shell_command_pattern_regexes():
    assert is_secrets_shell_command("ls .johnston .*secret*") is True
    assert is_secrets_shell_command("cat ~/.config/johnston/sec*") is True
    assert is_secrets_shell_command("cat ~/.johnston/*.json") is True
    assert is_secrets_shell_command("grep key ~/.johnston/*secret*") is True
    assert is_secrets_shell_command("cat .config/johnston/secrets.json") is True


def test_is_secrets_shell_command_absolute_pathsubs():
    assert is_secrets_shell_command("cat .johnston/secrets.json") is True
    assert is_secrets_shell_command("cat ~/.johnston/secrets.json") is True
    assert is_secrets_shell_command("cat $home/.johnston/secrets.json") is True
    assert is_secrets_shell_command("cat ${home}/.johnston/secrets.json") is True
    assert is_secrets_shell_command("cat ~/.config/johnston/secrets.json") is True
    assert is_secrets_shell_command("cat $home/.config/johnston/secrets.json") is True
    assert is_secrets_shell_command("cat ${home}/.config/johnston/secrets.json") is True


def test_is_secrets_shell_command_explicit_candidate(tmp_path):
    sec = str(tmp_path / "cfg" / "secrets.json")
    assert is_secrets_shell_command(f"cat {sec}", secrets_file=sec) is True
    assert is_secrets_shell_command("cat /other/file.txt", secrets_file=sec) is False


def test_is_secrets_shell_command_blank_candidate_skipped(tmp_path):
    sec = str(tmp_path / "cfg" / "secrets.json")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=["", sec],
    ):
        assert is_secrets_shell_command(f"cat {sec}") is True


def test_is_secrets_shell_command_candidate_realpath_error(tmp_path):
    sec = str(tmp_path / "cfg" / "secrets.json")
    orig_real = os.path.realpath

    def _fake_realpath(p):
        if p == os.path.abspath(os.path.expanduser(sec)):
            raise OSError("gone")
        return orig_real(p)

    with patch("os.path.realpath", side_effect=_fake_realpath):
        assert is_secrets_shell_command(f"cat {sec}", secrets_file=sec) is True


def test_is_secrets_shell_command_shlex_error_fallback():
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[""],
    ), patch("shlex.split", side_effect=ValueError("no closing quotation")):
        assert is_secrets_shell_command("cat secrets.json") is False


def test_is_secrets_shell_command_cd_tracking_and_resolution(tmp_path):
    sec = str(tmp_path / "cfg" / "secrets.json")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        # relative cd resolved against explicit cwd -> johnston dir
        assert (
            is_secrets_shell_command(
                "cd .johnston && cat secrets.json", cwd=str(tmp_path)
            )
            is True
        )
        # wrapper-command token skip
        assert (
            is_secrets_shell_command(
                "builtin cd .johnston && cat secrets.json", cwd=str(tmp_path)
            )
            is True
        )
        assert (
            is_secrets_shell_command(
                "command cd .johnston && cat secrets.json", cwd=str(tmp_path)
            )
            is True
        )
        # 'cd --' option strip
        assert (
            is_secrets_shell_command(
                "cd -- .johnston && cat secrets.json", cwd=str(tmp_path)
            )
            is True
        )
        # quoted cd target cleaned
        assert (
            is_secrets_shell_command(
                'cd ".johnston" && cat secrets.json', cwd=str(tmp_path)
            )
            is True
        )
        # direct tilde johnston dir
        assert is_secrets_shell_command("cd ~/.johnston && cat secrets.json") is True
        # non-johnston relative cd -> secrets access still undetected
        assert (
            is_secrets_shell_command(
                "cd src && cat secrets.json", cwd=str(tmp_path)
            )
            is False
        )
        # bare cd resets to home
        assert (
            is_secrets_shell_command("cd && cat ~/other.txt", cwd=str(tmp_path))
            is False
        )
        # inside johnston dir but command does not touch secrets
        assert (
            is_secrets_shell_command(
                "cd .johnston && cat secrets.json", cwd=str(tmp_path)
            )
            is True
        )
        # 'cd --' with no target after the separator
        assert (
            is_secrets_shell_command(
                "cd -- && cat ~/other.txt", cwd=str(tmp_path)
            )
            is False
        )


def test_is_secrets_shell_command_cd_resolved_in_secrets_dir(tmp_path, monkeypatch):
    sec = str(tmp_path / "cfg" / "secrets.json")
    monkeypatch.chdir(str(tmp_path))
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        # 'cfg' resolves into the secrets directory (dirname of the file)
        assert is_secrets_shell_command("cd cfg && cat secrets.json") is True


def test_is_secrets_shell_command_cd_resolved_johnston_symlink(tmp_path, monkeypatch):
    sec = str(tmp_path / "cfg" / "secrets.json")
    (tmp_path / ".johnston").mkdir()
    os.symlink(str(tmp_path / ".johnston"), str(tmp_path / "secretlink"))
    monkeypatch.chdir(str(tmp_path))
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        assert is_secrets_shell_command("cd secretlink && touch stats.json") is True
        # 'my.johnston' is caught by the tail regex
        assert is_secrets_shell_command("cd my.johnston && touch stats.json") is True


def test_is_secrets_shell_command_current_cwd_sensitive(tmp_path):
    sec = str(tmp_path / "cfg" / "secrets.json")
    johnston_dir = str(tmp_path / ".johnston")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        assert (
            is_secrets_shell_command("touch backup.json", cwd=johnston_dir) is True
        )
        assert (
            is_secrets_shell_command("rm unrelated.txt", cwd=johnston_dir) is False
        )
        # no cwd supplied -> not inside a secrets dir
        assert is_secrets_shell_command("touch backup.json") is False


def test_is_secrets_shell_command_json_glob_in_secrets_dir():
    """Inside a secrets dir, *.json tokens are blocked (line 254)."""
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=["/some/cfg/secrets.json"],
    ):
        assert (
            is_secrets_shell_command(
                "cd ~/.johnston && cat backup.json", cwd="/tmp"
            )
            is True
        )
        assert (
            is_secrets_shell_command(
                "cd ~/.johnston && cat sec.json", cwd="/tmp"
            )
            is True
        )
        assert (
            is_secrets_shell_command(
                "cd ~/.johnston && touch notes.md", cwd="/tmp"
            )
            is False
        )


def test_is_secrets_shell_command_empty_token_pipeline():
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=["/some/cfg/secrets.json"],
    ):
        assert is_secrets_shell_command("cat") is False


def test_is_secrets_shell_command_non_string_extract():
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=["/some/cfg/secrets.json"],
    ), patch.object(_pp, "extract_shell_subcommands", return_value=None):
        assert is_secrets_shell_command("cat secrets.json") is False


def test_is_secrets_shell_command_whitespace_subcommand_skipped():
    """Defensive branch: whitespace-only subcommand entries are skipped."""
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=["/some/cfg/secrets.json"],
    ), patch.object(_pp, "extract_shell_subcommands", return_value=["   "]):
        assert is_secrets_shell_command("cat secrets.json") is False


def test_is_secrets_shell_command_empty_tokens_skipped():
    """Defensive branch: shlex producing no tokens is skipped."""
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=["/some/cfg/secrets.json"],
    ), patch("shlex.split", return_value=[]):
        assert is_secrets_shell_command("cat secrets.json") is False


def test_is_secrets_shell_command_wrapper_without_arg_skipped(tmp_path):
    """Wrapper token with a single argument leaves tok_idx=0 (lines 216-217)."""
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=["/some/cfg/secrets.json"],
    ):
        # 'builtin' alone: first_tok stays 'builtin', not 'cd'
        assert is_secrets_shell_command("builtin && ls", cwd=str(tmp_path)) is False


def test_is_secrets_shell_command_cd_dash_none(tmp_path):
    """'cd --' with no further arg (line 222)."""
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=["/some/cfg/secrets.json"],
    ):
        assert is_secrets_shell_command("cd -- && cat ~/other.txt", cwd=str(tmp_path)) is False


def test_is_secrets_shell_command_empty_cleaned_token_in_secrets_dir(tmp_path):
    """Token that strips to empty inside a secrets dir (line 247)."""
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=["/some/cfg/secrets.json"],
    ):
        assert (
            is_secrets_shell_command('cd ~/.johnston && cat " "', cwd=str(tmp_path))
            is False
        )


def test_is_secrets_shell_command_direct_token_match(tmp_path):
    """Absolute path token that equals the candidate directly (line 261)."""
    sec = str(tmp_path / "cfg" / "secrets.json")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        assert is_secrets_shell_command(f"cat {sec}") is True


def test_is_secrets_shell_command_cwd_relative_parts_in_cmd(tmp_path):
    """Relative path containing '.' segments resolves inside the cwd."""
    sec = str(tmp_path / "cfg" / "secrets.json")
    rel = os.path.join("cfg", ".", "secrets.json")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        assert is_secrets_shell_command(f"cat {rel}", cwd=str(tmp_path)) is True


def test_is_secrets_shell_command_secrets_dir_join_relative_token(tmp_path):
    """A bare 'secrets.json' token joined onto a secrets-dir cwd matches."""
    sec = str(tmp_path / "cfg" / "secrets.json")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        assert is_secrets_shell_command("cat secrets.json", cwd=str(tmp_path / "cfg")) is True


def test_is_secrets_shell_command_token_join_exception_suppressed(tmp_path):
    sec = str(tmp_path / "cfg" / "secrets.json")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ), patch("os.path.join", side_effect=ValueError("bad")):
        assert is_secrets_shell_command("cat unrelated.txt", cwd=str(tmp_path)) is False


def test_is_secrets_shell_command_empty_candidate_direct_join(tmp_path):
    """Empty candidate + relative token -> no false positive (lines 266-268)."""
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[""],
    ):
        assert is_secrets_shell_command("cat secrets.json", cwd=str(tmp_path)) is False


def test_is_secrets_shell_command_non_string_paths_in_helper(tmp_path):
    """_is_johnston_dir guards against non-string/empty input (line 175)."""
    sec = str(tmp_path / "cfg" / "secrets.json")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        # cwd ignored when not a str, and a whitespace-only cwd is skipped too
        assert is_secrets_shell_command("cat secrets.json", cwd="   ") is False


def test_is_secrets_shell_command_helper_realpath_error(tmp_path):
    """_is_johnston_dir swallows realpath errors (lines 191-192)."""
    sec = str(tmp_path / "cfg" / "secrets.json")

    def _fake_realpath(p):
        raise OSError("gone")

    with patch("os.path.realpath", side_effect=_fake_realpath), patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        # cd target never resolves, so a plain file read is not blocked
        assert is_secrets_shell_command("cd config && ls") is False


def test_is_secrets_shell_command_literal_candidate_abs_in_cmd(tmp_path):
    """Literal candidate path inside the raw command (line 152)."""
    sec = str(tmp_path / "cfg" / "secrets.json")
    with patch(
        "johnston.core.domain.policies.policy_secrets.get_secrets_files",
        return_value=[sec],
    ):
        assert is_secrets_shell_command(f"cat {sec}") is True


def test_is_secrets_shell_command_thread_safety_smoke():
    """Many parallel evaluations must not raise and must stay consistent."""
    hits: list = []
    misses: list = []
    lock = threading.Lock()

    def _run(cmd: str) -> bool:
        return is_secrets_shell_command(cmd)

    def _target(cmd: str) -> None:
        with lock:
            (hits if _run(cmd) else misses).append(cmd)

    threads = []
    for cmd in ("cat ~/.johnston/secrets.json", "cd src && cat secrets.json"):
        for _ in range(5):
            t = threading.Thread(target=_target, args=(cmd,), daemon=True)
            threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert len(hits) == 5 and all("secrets.json" in c for c in hits)
    assert len(misses) == 5 and all("src" in c for c in misses)
