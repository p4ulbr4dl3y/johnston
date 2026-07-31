import os
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from core.platform_utils import get_clipboard_image_or_file, is_image_file, johnston_config_dir, supports_pty


class TestPlatformUtils(unittest.TestCase):
    def test_windows_config_dir_uses_appdata(self):
        with patch("core.platform_utils.is_windows", return_value=True), patch.dict(
            os.environ, {"APPDATA": r"C:\Users\me\AppData\Roaming"}
        ):
            self.assertEqual(johnston_config_dir(), Path(r"C:\Users\me\AppData\Roaming") / "johnston")

    def test_windows_does_not_use_pty(self):
        with patch("core.platform_utils.is_windows", return_value=True):
            self.assertFalse(supports_pty())

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

