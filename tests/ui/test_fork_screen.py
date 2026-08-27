import unittest
from unittest.mock import MagicMock

from textual.widgets import OptionList

from widgets.presentation.screens.fork import FORK_CURRENT_STATE, ForkScreen


class TestForkScreen(unittest.IsolatedAsyncioTestCase):
    def test_fork_screen_formatting_and_fit(self):
        user_messages = [
            (0, "first message\nwith multiline"),
            (1, "second message"),
        ]
        screen = ForkScreen(user_messages)
        self.assertFalse(screen.fit_content)
        self.assertEqual(len(screen.raw_options), 3)
        self.assertNotIn("\n", screen.raw_options[0])
        self.assertIn("first message with multiline", screen.raw_options[0])
        self.assertIn("second message", screen.raw_options[1])
        self.assertIn("Current state", screen.raw_options[2])
        self.assertEqual(screen.default_value, FORK_CURRENT_STATE)
        self.assertEqual(screen.raw_items[-1], FORK_CURRENT_STATE)

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

    def test_fork_screen_selection_current_state(self):
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
        mock_event.option_index = 2
        screen.on_option_list_option_selected(mock_event)

        self.assertEqual(dismissed_val, FORK_CURRENT_STATE)

    def test_fork_screen_search_filtering(self):
        user_messages = [
            (0, "apple banana"),
            (1, "cherry orange"),
        ]
        screen = ForkScreen(user_messages)
        self.assertTrue(screen.show_search)

        screen._filter_options("banana")
        self.assertEqual(len(screen.filtered_items), 1)
        self.assertEqual(screen.filtered_items[0], 0)

        screen._filter_options("cherry")
        self.assertEqual(len(screen.filtered_items), 1)
        self.assertEqual(screen.filtered_items[0], 1)

        screen._filter_options("")
        self.assertEqual(len(screen.filtered_items), 3)

    async def test_fork_screen_default_highlight(self):
        from textual.app import App

        class MockApp(App):
            pass

        app = MockApp()
        async with app.run_test() as pilot:
            screen = ForkScreen([(0, "msg 1"), (1, "msg 2")])
            await app.push_screen(screen)
            await pilot.pause()
            opt_list = screen.query_one(OptionList)
            self.assertEqual(opt_list.highlighted, 2)
            self.assertEqual(screen.raw_items[opt_list.highlighted], FORK_CURRENT_STATE)


