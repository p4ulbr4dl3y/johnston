import unittest

from widgets.presentation.widgets.chat_notch import ChatNotch, ChatNotchContainer


class TestChatNotch(unittest.TestCase):
    def test_init_and_toggle(self):
        notch = ChatNotch()
        self.assertFalse(notch.is_expanded)
        notch.toggle_expanded()
        self.assertTrue(notch.is_expanded)
        notch.on_click()
        self.assertFalse(notch.is_expanded)

    def test_render_collapsed_and_expanded(self):
        notch = ChatNotch()
        col = notch._render_collapsed()
        self.assertIsNotNone(col)
        exp = notch._render_expanded()
        self.assertIsNotNone(exp)

    def test_container_compose(self):
        container = ChatNotchContainer()
        children = list(container.compose())
        self.assertEqual(len(children), 1)
        self.assertIsInstance(children[0], ChatNotch)
        self.assertEqual(children[0].id, "chat-notch")
