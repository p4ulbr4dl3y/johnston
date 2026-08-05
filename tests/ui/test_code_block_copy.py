import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from textual.widgets import Button

from widgets.chat_view import CustomMarkdownFence


class TestCodeBlockCopy(unittest.TestCase):
    @patch.object(CustomMarkdownFence, "app", new_callable=PropertyMock)
    def test_custom_markdown_fence_button_press(self, mock_app_prop):
        mock_app = MagicMock()
        mock_app_prop.return_value = mock_app

        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        fence.code = "x = 42"

        event = MagicMock(spec=Button.Pressed)
        event.button = MagicMock(spec=Button)
        event.button.classes = {"fence-copy-btn"}

        fence.on_button_pressed(event)

        mock_app.copy_to_clipboard.assert_called_once_with("x = 42")
        event.stop.assert_called_once()

    def test_custom_markdown_fence_allow_horizontal_scroll(self):
        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        self.assertFalse(fence.allow_horizontal_scroll)

    def test_custom_markdown_fence_compose_without_theme(self):
        from textual._context import active_app
        mock_app = MagicMock()
        mock_app._compose_stacks = [[]]
        token = active_app.set(mock_app)
        try:
            fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
            fence.lexer = "python"
            fence.code = "print(1)"
            res = list(fence.compose())
            self.assertTrue(len(res) > 0)
        finally:
            active_app.reset(token)


if __name__ == "__main__":
    unittest.main()
