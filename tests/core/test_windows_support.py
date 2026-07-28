import os
import unittest
from pathlib import Path
from unittest.mock import patch

from core.platform_utils import johnston_config_dir, supports_pty


class TestPlatformUtils(unittest.TestCase):
    def test_windows_config_dir_uses_appdata(self):
        with patch("core.platform_utils.is_windows", return_value=True), patch.dict(
            os.environ, {"APPDATA": r"C:\Users\me\AppData\Roaming"}
        ):
            self.assertEqual(johnston_config_dir(), Path(r"C:\Users\me\AppData\Roaming") / "johnston")

    def test_windows_does_not_use_pty(self):
        with patch("core.platform_utils.is_windows", return_value=True):
            self.assertFalse(supports_pty())
