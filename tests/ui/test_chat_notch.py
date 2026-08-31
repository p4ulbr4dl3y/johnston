import unittest

from widgets.presentation.widgets.chat_notch import ChatNotch, ChatNotchContainer


class TestChatNotch(unittest.TestCase):
    def test_init_and_status(self):
        notch = ChatNotch()
        self.assertEqual(notch.status_text, "Ready")
        notch.set_status("Generating...")
        self.assertEqual(notch.status_text, "Generating...")

    def test_refresh_notch(self):
        notch = ChatNotch()
        notch.refresh_notch()

    def test_container_compose(self):
        container = ChatNotchContainer()
        children = list(container.compose())
        self.assertEqual(len(children), 1)
        self.assertIsInstance(children[0], ChatNotch)
        self.assertEqual(children[0].id, "chat-notch")
