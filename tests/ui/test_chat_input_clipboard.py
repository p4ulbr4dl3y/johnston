import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from widgets.chat_input import ChatInput


class TestChatInputClipboard(unittest.TestCase):
    def test_try_paste_clipboard_image_file_path(self):
        chat_input = ChatInput()
        chat_input.insert = MagicMock()
        chat_input._on_input_change = MagicMock()

        with patch("core.platform_utils.get_clipboard_image_or_file", return_value=("/tmp/sample.png", None)):
            res = chat_input.try_paste_clipboard_image()
            self.assertTrue(res)
            chat_input.insert.assert_called_once_with("@/tmp/sample.png ")
            chat_input._on_input_change.assert_called_once()

    def test_try_paste_clipboard_image_data(self):
        chat_input = ChatInput()
        chat_input.update_attachment_bar = MagicMock()

        mock_img = Image.new("RGB", (100, 50))
        with patch("core.platform_utils.get_clipboard_image_or_file", return_value=(None, mock_img)), patch(
            "os.makedirs"
        ), patch("os.path.getsize", return_value=1024), patch.object(Image.Image, "save"):
            res = chat_input.try_paste_clipboard_image()
            self.assertTrue(res)
            self.assertEqual(len(chat_input.clipboard_attachments), 1)
            self.assertEqual(chat_input.clipboard_attachments[0].width, 100)
            self.assertEqual(chat_input.clipboard_attachments[0].height, 50)
            chat_input.update_attachment_bar.assert_called_once()

    def test_try_paste_clipboard_image_none(self):
        chat_input = ChatInput()
        with patch("core.platform_utils.get_clipboard_image_or_file", return_value=(None, None)):
            res = chat_input.try_paste_clipboard_image()
            self.assertFalse(res)
            self.assertEqual(len(chat_input.clipboard_attachments), 0)
