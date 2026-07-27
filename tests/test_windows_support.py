import os
import unittest
from pathlib import Path
from unittest.mock import patch

from core.platform_utils import johnston_config_dir, supports_pty
from core.shell_guard import analyze_shell_command


class TestShellGuard(unittest.TestCase):
    def test_blocks_windows_destructive_commands(self):
        for command in ("del important.txt", "Remove-Item -Recurse .", "rmdir /s build"):
            with self.subTest(command=command):
                is_safe, reason = analyze_shell_command(command)
                self.assertFalse(is_safe)
                self.assertIn("unsafe command", reason)

    def test_blocks_windows_sensitive_paths(self):
        is_safe, reason = analyze_shell_command(r'type "%USERPROFILE%\.ssh\id_rsa"')
        self.assertFalse(is_safe)
        self.assertIn("sensitive path", reason)


class TestPlatformUtils(unittest.TestCase):
    def test_windows_config_dir_uses_appdata(self):
        with patch("core.platform_utils.is_windows", return_value=True), patch.dict(
            os.environ, {"APPDATA": r"C:\Users\me\AppData\Roaming"}
        ):
            self.assertEqual(johnston_config_dir(), Path(r"C:\Users\me\AppData\Roaming") / "johnston")

    def test_windows_does_not_use_pty(self):
        with patch("core.platform_utils.is_windows", return_value=True):
            self.assertFalse(supports_pty())
