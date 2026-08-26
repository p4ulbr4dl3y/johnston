import unittest
from unittest.mock import MagicMock

from textual.widgets import Input

from widgets.presentation.screens.rename_session import RenameSessionScreen


class TestRenameSessionScreen(unittest.TestCase):
    def test_rename_session_screen_input_submission(self):
        screen = RenameSessionScreen(current_title="Old Title")
        dismissed_val = None

        def mock_dismiss(val):
            nonlocal dismissed_val
            dismissed_val = val

        screen.dismiss = mock_dismiss

        mock_event = MagicMock(spec=Input.Submitted)
        mock_event.value = "  New Fancy Title  "
        screen.on_input_submitted(mock_event)

        self.assertEqual(dismissed_val, "New Fancy Title")

    def test_rename_session_screen_cancel(self):
        screen = RenameSessionScreen(current_title="Old Title")
        dismissed_val = "initial"

        def mock_dismiss(val):
            nonlocal dismissed_val
            dismissed_val = val

        screen.dismiss = mock_dismiss
        screen.action_cancel()
        self.assertIsNone(dismissed_val)
