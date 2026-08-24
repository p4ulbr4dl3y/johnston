import unittest
from unittest.mock import MagicMock

from textual.widgets import OptionList

from core.application.session.actions import RewindEntry
from widgets.presentation.screens.rewind import RewindScreen


class TestRewindScreen(unittest.TestCase):
    def test_rewind_multiline_formatting(self):
        user_messages = [
            RewindEntry(0, "@/Users/yegor/testing/interactive_test.sh\nне чита..."),
            RewindEntry(1, "line 1\r\nline 2\r\nline 3"),
        ]
        screen = RewindScreen(user_messages)
        self.assertEqual(len(screen.raw_options), 2)
        self.assertNotIn("\n", screen.raw_options[0])
        self.assertNotIn("\r", screen.raw_options[0])
        self.assertIn("@/Users/yegor/testing/", screen.raw_options[0])
        self.assertNotIn("\n", screen.raw_options[1])
        self.assertIn("line 1 line 2 line 3", screen.raw_options[1])

    def test_checkpoints_disabled(self):
        user_messages = [
            RewindEntry(0, "hello world", "no checkpoint"),
            RewindEntry(1, "second message", "+5 / -2"),
        ]
        screen_enabled = RewindScreen(user_messages, checkpoints_enabled=True)
        self.assertIn("[no checkpoint]", screen_enabled.raw_options[0])
        self.assertIn("[+5 / -2]", screen_enabled.raw_options[1])

        screen_disabled = RewindScreen(user_messages, checkpoints_enabled=False)
        self.assertNotIn("[no checkpoint]", screen_disabled.raw_options[0])
        self.assertNotIn("[+5 / -2]", screen_disabled.raw_options[1])
        self.assertEqual(screen_disabled.raw_options[0], "hello world")
        self.assertEqual(screen_disabled.raw_options[1], "second message")

    def test_step1_to_step2_and_selection_modes(self):
        user_messages = [
            RewindEntry(0, "first message", "+3 / -1"),
            RewindEntry(1, "second message", "+10 / -5"),
        ]
        screen = RewindScreen(user_messages, checkpoints_enabled=True)
        dismissed_val = None

        def mock_dismiss(val):
            nonlocal dismissed_val
            dismissed_val = val

        screen.dismiss = mock_dismiss

        # Step 1: select index 0
        mock_event = MagicMock(spec=OptionList.OptionSelected)
        mock_event.option_index = 0
        screen.on_option_list_option_selected(mock_event)

        self.assertEqual(screen.step, 2)
        self.assertEqual(screen.selected_entry, user_messages[0])
        self.assertIsNone(dismissed_val)
        self.assertEqual(len(screen.filtered_items), 2)
        self.assertEqual(screen.filtered_items, ["both", "conversation"])

        # Step 2: choose 'conversation'
        screen._show_step_2(user_messages[1])
        mock_event.option_index = 1
        screen.on_option_list_option_selected(mock_event)
        self.assertIsNotNone(dismissed_val)
        self.assertEqual(dismissed_val.index, 1)
        self.assertFalse(dismissed_val.restore_code)

        # Step 2: choose 'both'
        screen._show_step_2(user_messages[0])
        mock_event.option_index = 0
        screen.on_option_list_option_selected(mock_event)
        self.assertIsNotNone(dismissed_val)
        self.assertEqual(dismissed_val.index, 0)
        self.assertTrue(dismissed_val.restore_code)

    def test_step2_back_to_step1_on_action_cancel(self):
        user_messages = [RewindEntry(0, "message 0", "+1 / -1")]
        screen = RewindScreen(user_messages, checkpoints_enabled=True)
        dismissed_val = None

        def mock_dismiss(val):
            nonlocal dismissed_val
            dismissed_val = val

        screen.dismiss = mock_dismiss

        screen._show_step_2(user_messages[0])
        self.assertEqual(screen.step, 2)

        # Escape key triggers action_cancel -> back to step 1
        screen.action_cancel()
        self.assertEqual(screen.step, 1)
        self.assertIsNone(screen.selected_entry)
        self.assertIsNone(dismissed_val)

        # Escape on step 1 -> dismisses with None
        screen.action_cancel()
        self.assertIsNone(dismissed_val)

    def test_disabled_checkpoints_direct_dismiss(self):
        user_messages = [RewindEntry(0, "msg 0")]
        screen = RewindScreen(user_messages, checkpoints_enabled=False)
        dismissed_val = None

        def mock_dismiss(val):
            nonlocal dismissed_val
            dismissed_val = val

        screen.dismiss = mock_dismiss

        mock_event = MagicMock(spec=OptionList.OptionSelected)
        mock_event.option_index = 0
        screen.on_option_list_option_selected(mock_event)

        self.assertIsNotNone(dismissed_val)
        self.assertEqual(dismissed_val.index, 0)
        self.assertFalse(dismissed_val.restore_code)

    def test_no_changes_direct_dismiss(self):
        user_messages = [
            RewindEntry(0, "message with no changes", "no changes"),
            RewindEntry(1, "message with no checkpoint", "no checkpoint"),
        ]
        screen = RewindScreen(user_messages, checkpoints_enabled=True)
        dismissed_val = None

        def mock_dismiss(val):
            nonlocal dismissed_val
            dismissed_val = val

        screen.dismiss = mock_dismiss

        mock_event = MagicMock(spec=OptionList.OptionSelected)
        # Selecting message 0 ("no changes")
        mock_event.option_index = 0
        screen.on_option_list_option_selected(mock_event)
        self.assertIsNotNone(dismissed_val)
        self.assertEqual(dismissed_val.index, 0)
        self.assertFalse(dismissed_val.restore_code)

        # Selecting message 1 ("no checkpoint")
        dismissed_val = None
        mock_event.option_index = 1
        screen.on_option_list_option_selected(mock_event)
        self.assertIsNotNone(dismissed_val)
        self.assertEqual(dismissed_val.index, 1)
        self.assertFalse(dismissed_val.restore_code)
