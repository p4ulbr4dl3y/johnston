import os
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from core.platform_utils import (
    get_clipboard_image_or_file,
    is_image_file,
    johnston_config_dir,
    shell_env,
)


class TestPlatformUtils(unittest.TestCase):
    def test_windows_config_dir_uses_appdata(self):
        with patch("core.platform_utils.is_windows", return_value=True), patch.dict(
            os.environ, {"APPDATA": r"C:\Users\me\AppData\Roaming"}
        ):
            self.assertEqual(johnston_config_dir(), Path(r"C:\Users\me\AppData\Roaming") / "johnston")

    def test_shell_env_contains_noninteractive_variables(self):
        env = shell_env()
        self.assertEqual(env.get("CI"), "1")
        self.assertEqual(env.get("DEBIAN_FRONTEND"), "noninteractive")
        self.assertEqual(env.get("FORCE_COLOR"), "0")
        self.assertEqual(env.get("CLI_AUTO_PROMPT"), "0")
        self.assertEqual(env.get("PAGER"), "cat")
        self.assertEqual(env.get("GIT_PAGER"), "cat")
        self.assertEqual(env.get("TERM"), "dumb")
        self.assertEqual(env.get("NO_COLOR"), "1")

    def test_is_image_file(self):
        self.assertTrue(is_image_file("photo.png"))
        self.assertTrue(is_image_file("image.JPG"))
        self.assertTrue(is_image_file("/path/to/graphic.svg"))
        self.assertFalse(is_image_file("document.pdf"))
        self.assertFalse(is_image_file("script.py"))

    def test_get_clipboard_image_from_pil(self):
        mock_img = Image.new("RGB", (10, 10))
        with patch("PIL.ImageGrab.grabclipboard", return_value=mock_img):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertEqual(img, mock_img)

    def test_get_clipboard_file_from_pil(self):
        with patch("PIL.ImageGrab.grabclipboard", return_value=["/tmp/test.png"]), patch(
            "os.path.exists", return_value=True
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertEqual(file_path, "/tmp/test.png")
            self.assertIsNone(img)

    def test_get_clipboard_empty_returns_none(self):
        with patch("PIL.ImageGrab.grabclipboard", return_value=None), patch(
            "core.platform_utils.is_windows", return_value=True
        ):
            file_path, img = get_clipboard_image_or_file()
            self.assertIsNone(file_path)
            self.assertIsNone(img)

