"""Unit tests for the Windows restricted-token sandbox runner (pure helpers only)."""
import base64
import os
from unittest.mock import patch

from core.infrastructure.platform import win_sandbox_runner as r


def test_encode_ps_command_roundtrip():
    enc = r.encode_ps_command("echo привет")
    decoded = base64.b64decode(enc).decode("utf-16-le")
    assert decoded.startswith(r.PS_UTF8_PREAMBLE)
    assert decoded.endswith("echo привет")


def test_build_shell_argv_powershell():
    argv = r.build_shell_argv("C:\\Program Files\\PowerShell\\7\\pwsh.exe", "echo hi")
    assert argv[:4] == ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
    # -EncodedCommand payload decodes back to preamble + command.
    assert base64.b64decode(argv[5]).decode("utf-16-le").endswith("echo hi")


def test_build_shell_argv_cmd():
    argv = r.build_shell_argv("cmd.exe", 'echo "a b"')
    assert argv == ["/d", "/s", "/c", 'echo "a b"']


def test_format_command_line_quoting():
    line = r.format_command_line("C:\\Program Files\\pwsh.exe", ["-EncodedCommand", "aGVsbG8="])
    assert '"C:\\Program Files\\pwsh.exe"' in line
    assert "-EncodedCommand aGVsbG8=" in line


def test_select_shell_prefers_pwsh():
    def which(name):
        return {"pwsh": "C:\\pwsh.exe", "powershell": None, "cmd": None}.get(name)

    with patch("shutil.which", side_effect=which):
        assert r.select_shell() == "C:\\pwsh.exe"


def test_select_shell_falls_back_to_comspec():
    with patch("shutil.which", return_value=None), patch.dict(os.environ, {"ComSpec": "C:\\Windows\\cmd.exe"}):
        assert r.select_shell() == "C:\\Windows\\cmd.exe"
