"""Edge-case tests for core/linters_manager.py.

Focus: injection safety, timeout, non-zero/killed exit codes, unicode/binary
output, empty/giant output, bad path types, unsupported extensions, missing
linter binaries, and config selection.

These exercise _exec_cmd / run_for / render_cmd directly with harmless
subprocesses. No system-dangerous commands are ever run.
"""

import json
import os
import tempfile
import time
from unittest.mock import patch

from core.linters_manager import LintersManager, _exec_cmd


def _make_manager(tmp_path):
    cfg = tmp_path / "linters.json"
    m = LintersManager(config_file=str(cfg))
    m.config_file = str(cfg)
    return m


def _write_config(m, data):
    with open(m.config_file, "w", encoding="utf-8") as f:
        json.dump(data, f)


# --------------------------------------------------------------------- files


async def test_run_for_nonexistent_file_returns_empty(tmp_path):
    m = _make_manager(tmp_path)
    assert await m.run_for(str(tmp_path / "ghost.py")) == ""


async def test_run_for_unknown_extension_returns_empty(tmp_path):
    m = _make_manager(tmp_path)
    f = tmp_path / "notes.txt"
    f.write_text("hello")
    assert await m.run_for(str(f)) == ""


async def test_run_for_unsupported_non_py_md_type(tmp_path):
    m = _make_manager(tmp_path)
    for name in ("a.md", "a.rst", "a.xyz", "a"):
        f = tmp_path / name
        f.write_text("x")
        assert await m.run_for(str(f)) == "", f"expected empty for {name}"


async def test_run_for_none_path_safe(tmp_path):
    """Fixed: run_for(None) no longer crashes; returns empty string."""
    m = _make_manager(tmp_path)
    assert await m.run_for(None) == ""


async def test_run_for_list_path_safe(tmp_path):
    """Fixed: run_for(list) no longer crashes; returns empty string."""
    m = _make_manager(tmp_path)
    assert await m.run_for(["a.py"]) == ""


# ------------------------------------------------------------- exec exit codes


async def test_exec_exit_zero_returns_none():
    assert await _exec_cmd(["true"]) is None


async def test_exec_exit_nonzero_with_output_returns_text():
    out = await _exec_cmd(["sh", "-c", "echo oops; exit 1"])
    assert out is not None
    assert "oops" in out


async def test_exec_exit_nonzero_empty_output_reports_exit():
    """Fixed: non-zero exit with empty stdout is surfaced, not swallowed."""
    out = await _exec_cmd(["sh", "-c", "exit 1"])
    assert out is not None
    assert "exited with code 1" in out


async def test_exec_high_exit_code_returns_output():
    out = await _exec_cmd(["sh", "-c", "echo boom; exit 42"])
    assert "boom" in out


async def test_exec_signal_killed_reports_exit():
    """Fixed: KILLED (returncode -9) with empty output is surfaced, not swallowed."""
    out = await _exec_cmd(["sh", "-c", "kill -9 $$"])
    assert out is not None
    assert "-9" in out


# ------------------------------------------------------------------- timeout


async def test_exec_timeout_kills_hung_linter():
    start = time.monotonic()
    out = await _exec_cmd(["sh", "-c", "sleep 100"])
    elapsed = time.monotonic() - start
    assert out is None
    assert elapsed < 10, f"timeout did not kill subprocess, took {elapsed:.1f}s"


# ------------------------------------------------------- unicode/binary output


async def test_exec_unicode_nonzero_output_decoded():
    out = await _exec_cmd(["sh", "-c", "printf '\\xc3\\xa9 \\xe2\\x82\\xac caf\\xc3\\xa9'; exit 1"])
    assert out is not None
    assert "café" in out


async def test_exec_binary_output_does_not_crash():
    out = await _exec_cmd(["sh", "-c", "printf '\\x80\\xff\\x00\\xfe'; exit 1"])
    # decode_output uses errors=replace: must not raise, returns str.
    assert isinstance(out, str)


async def test_exec_giant_output_decoded():
    out = await _exec_cmd(["sh", "-c", "yes 'err line' | head -c 200000; exit 1"])
    assert out is not None
    assert len(out) > 1000


async def test_run_for_giant_output_truncated(tmp_path):
    m = _make_manager(tmp_path)
    _write_config(
        m,
        {
            "linters": {
                "big": {
                    "cmd": ["sh", "-c", "i=0; while [ $i -lt 100 ]; do echo err$i; i=$((i+1)); done; exit 1"],
                    "extensions": [".big"],
                    "custom": True,
                    "enabled": True,
                }
            }
        },
    )
    (tmp_path / "x.big").write_text("x")
    with patch.object(m, "is_available", return_value=True):
        res = await m.run_for(str(tmp_path / "x.big"))
    assert "ERR:" in res
    assert "(90 more lines)" in res, res
    assert res.count("\n") <= 12, res  # 10 kept lines + '...more' + \n\nERR prefix = 12


async def test_run_for_clean_output_strips_noise(tmp_path):
    m = _make_manager(tmp_path)
    _write_config(
        m,
        {
            "linters": {
                "noisy": {
                    "cmd": ["sh", "-c", "echo 'Building stuff'; echo 'Downloading x'; echo 'Real error'; exit 1"],
                    "extensions": [".ny"],
                    "custom": True,
                    "enabled": True,
                }
            }
        },
    )
    (tmp_path / "x.ny").write_text("x")
    with patch.object(m, "is_available", return_value=True):
        res = await m.run_for(str(tmp_path / "x.ny"))
    assert "Real error" in res
    assert "Building" not in res
    assert "Downloading" not in res


async def test_run_for_empty_warning_output(tmp_path):
    """Successful lint (exit 0) -> no ERR block."""
    m = _make_manager(tmp_path)
    _write_config(
        m,
        {
            "linters": {
                "ok": {"cmd": ["sh", "-c", "echo clean; exit 0"], "extensions": [".ok"],
                       "custom": True, "enabled": True}
            }
        },
    )
    with patch.object(m, "is_available", return_value=True):
        res = await m.run_for(str(tmp_path / "x.ok"))
    assert res == ""


# ------------------------------------------------------------ path safety


def test_render_cmd_path_with_spaces_and_quotes():
    lint = {"cmd": ["tool", "{file}"]}
    path = '/tmp/has space/"quote"/$dollar; semi'
    cmd = LintersManager.render_cmd(lint, path)
    assert cmd == ["tool", path], "path must be passed as a single literal argv"


async def test_exec_no_shell_injection():
    """_exec_cmd uses create_subprocess_exec (no shell): a payload argv is
    passed literally, never executed as a command."""
    target = os.path.join(tempfile.gettempdir(), "johnston_pwned_test")
    if os.path.exists(target):
        os.remove(target)
    payload = f"$(touch {target})"
    try:
        out = await _exec_cmd(["python3", "-c", "import sys; print('argv=', sys.argv[1])", payload])
        # exit 0 -> returns None; the point is the file must NOT exist.
        assert out is None
        assert not os.path.exists(target), "shell injection executed!"
    finally:
        if os.path.exists(target):
            os.remove(target)


async def test_exec_dollar_and_semicolon_literal(tmp_path):
    """Path with ; and $ chars passed as single argv, no command splitting."""
    f = tmp_path / "weird;name$ok.py"
    f.write_text("x=1")
    m = _make_manager(tmp_path)
    _write_config(
        m,
        {
            "linters": {
                "py": {
                    "cmd": ["python3", "-c", "import sys; print('got', sys.argv[1])", "{file}"],
                    "extensions": [".py"],
                    "custom": True,
                    "enabled": True,
                }
            }
        },
    )
    with patch.object(m, "is_available", return_value=True):
        res = await m.run_for(str(f))
    # linter exits 0 -> no ERR block; ensures nothing crashed on weird path.
    assert res == ""


# ------------------------------------------------------------ linter presence


async def test_missing_binary_defines_unavailable(tmp_path):
    m = _make_manager(tmp_path)
    _write_config(m, {"linters": {"python": {"enabled": True}}})
    with patch.object(m, "is_available", return_value=False):
        found = m.get_for_extension(".py")
    assert found == [], "unavailable linter must be filtered out"


async def test_run_for_skips_unavailable_linters(tmp_path):
    m = _make_manager(tmp_path)
    _write_config(m, {"linters": {"python": {"enabled": True}}})
    with patch.object(m, "is_available", return_value=False):
        res = await m.run_for(str(tmp_path / "x.py"))
    assert res == ""


# ------------------------------------------------------------- config selection


async def test_custom_config_overrides_preset_cmd(tmp_path):
    m = _make_manager(tmp_path)
    _write_config(
        m,
        {
            "linters": {
                "python": {
                    "enabled": True,
                    "cmd": ["sh", "-c", "echo custom-python; exit 1"],
                }
            }
        },
    )
    (tmp_path / "x.py").write_text("x=1")
    with patch.object(m, "is_available", return_value=True):
        res = await m.run_for(str(tmp_path / "x.py"))
    assert "custom-python" in res


def test_missing_config_file_loads_presets(tmp_path):
    m = _make_manager(tmp_path)
    if os.path.exists(m.config_file):
        os.remove(m.config_file)
    linters = m.load_linters()
    assert any(it["name"] == "python" for it in linters)


async def test_run_for_empty_lint_list_ok(tmp_path):
    m = _make_manager(tmp_path)
    _write_config(m, {"linters": {}})
    assert await m.run_for(str(tmp_path / "x.ts")) == ""
