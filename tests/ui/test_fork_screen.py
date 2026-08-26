import unittest
from unittest.mock import MagicMock

from textual.widgets import OptionList

from widgets.presentation.screens.fork import ForkScreen


class TestForkScreen(unittest.TestCase):
    def test_fork_screen_formatting(self):
        user_messages = [
            (0, "first message\nwith multiline"),
            (1, "second message"),
        ]
        screen = ForkScreen(user_messages)
        self.assertEqual(len(screen.raw_options), 2)
        self.assertNotIn("\n", screen.raw_options[0])
        self.assertIn("first message with multiline", screen.raw_options[0])
        self.assertIn("second message", screen.raw_options[1])

    def test_fork_screen_selection(self):
        user_messages = [
            (0, "first message"),
            (1, "second message"),
        ]
        screen = ForkScreen(user_messages)
        dismissed_val = None

        def mock_dismiss(val):
            nonlocal dismissed_val
            dismissed_val = val

        screen.dismiss = mock_dismiss

        mock_event = MagicMock(spec=OptionList.OptionSelected)
        mock_event.option_index = 1
        screen.on_option_list_option_selected(mock_event)

        self.assertEqual(dismissed_val, 1)
