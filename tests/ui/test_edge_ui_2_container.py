"""Edge-case tests for widgets/chat_container (ChatView).

Message-list edge cases: welcome state, rollback bounds, dedup.
"""

import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from widgets.chat_container import ChatView
from widgets.chat_messages import UserMessage
from widgets.chat_welcome import WelcomeWidget


class TestChatViewWelcome(unittest.TestCase):
    def test_check_welcome_with_no_children_mounts(self):
        view = ChatView(show_welcome=True)
        view.query = MagicMock(return_value=[])
        view.mount = MagicMock()
        with patch.object(ChatView, "children", new_callable=PropertyMock, return_value=[]):
            view.check_welcome()
        view.mount.assert_called_once()
        self.assertIsInstance(view.mount.call_args[0][0], WelcomeWidget)

    def test_check_welcome_with_messages_clears(self):
        view = ChatView(show_welcome=True)
        wel = WelcomeWidget()
        wel.remove = MagicMock()
        view.query = MagicMock(return_value=[wel])
        with patch.object(ChatView, "children", new_callable=PropertyMock, return_value=["msg"]):
            view.check_welcome()
        wel.remove.assert_called_once()

    def test_rollback_to_negative_index(self):
        view = ChatView()
        child1, child2 = UserMessage("a", markup=False), UserMessage("b", markup=False)
        child1.remove = MagicMock()
        child2.remove = MagicMock()
        with patch.object(ChatView, "children", new_callable=PropertyMock, return_value=[child1, child2]):
            with patch.object(ChatView, "check_welcome"):
                view.rollback_to(-5)
        child1.remove.assert_called_once()
        child2.remove.assert_called_once()

    def test_is_at_bottom_threshold(self):
        view = ChatView()
        with patch.object(ChatView, "max_scroll_y", new_callable=PropertyMock, return_value=100):
            with patch.object(ChatView, "scroll_y", new_callable=PropertyMock, return_value=98):
                self.assertTrue(view.is_at_bottom(3))  # 100 - 98 = 2 <= 3


if __name__ == "__main__":
    unittest.main()
