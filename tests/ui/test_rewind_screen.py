import unittest
from unittest.mock import MagicMock

from textual.widgets import OptionList

from core.application.session.actions import RewindEntry
from widgets.presentation.screens.rewind import RewindScreen, RewindSelection


class TestRewindScreen(unittest.IsolatedAsyncioTestCase):
    def test_rewind_multiline_formatting(self):
        user_messages = [
            RewindEntry(0, "@/Users/yegor/testing/interactive_test.sh\nне чита..."),
            RewindEntry(1, "line 1\r\nline 2\r\nline 3"),
        ]
        screen = RewindScreen(user_messages)
        self.assertEqual(len(screen.raw_options), 3)
        self.assertIn("cancel rollback", screen.raw_options[2])
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
        self.assertIn("no checkpoint", screen_enabled.raw_options[0])
        self.assertIn("+5 / -2", screen_enabled.raw_options[1])

        screen_disabled = RewindScreen(user_messages, checkpoints_enabled=False)
        self.assertNotIn("no checkpoint", screen_disabled.raw_options[0])
        self.assertNotIn("+5 / -2", screen_disabled.raw_options[1])
        self.assertEqual(screen_disabled.raw_options[0], "hello world")
        self.assertEqual(screen_disabled.raw_options[1], "second message")

    def test_selection_pushes_rewind_action_screen(self):
        from widgets.presentation.screens.rewind_action import RewindActionScreen

        user_messages = [
            RewindEntry(0, "first message", "+3 / -1"),
            RewindEntry(1, "second message", "+10 / -5"),
        ]
        screen = RewindScreen(user_messages, checkpoints_enabled=True)
        mock_app = MagicMock()

        # Selecting index 0 with changes pushes RewindActionScreen
        mock_event = MagicMock(spec=OptionList.OptionSelected)
        mock_event.option_index = 0
        with unittest.mock.patch.object(RewindScreen, "app", new=mock_app):
            screen.on_option_list_option_selected(mock_event)
            mock_app.push_screen.assert_called_once()

            args, kwargs = mock_app.push_screen.call_args
            action_screen = args[0]
            cb = kwargs.get("callback")
            self.assertIsInstance(action_screen, RewindActionScreen)
            self.assertEqual(action_screen.entry, user_messages[0])

            # Callback with selection dismisses RewindScreen
            screen.dismiss = lambda val: setattr(screen, "_dismissed", val)
            cb(RewindSelection(index=0, restore_code=True))
            self.assertEqual(screen._dismissed.index, 0)
            self.assertTrue(screen._dismissed.restore_code)

    def test_rewind_action_screen_options_and_diff(self):
        from widgets.presentation.screens.rewind_action import RewindActionScreen

        entry = RewindEntry(0, "first message", "+3 / -1", changed_files=["a.py"])
        screen = RewindActionScreen(entry)
        dismissed_val = None
        screen.dismiss = lambda val: nonlocal_assign(val)

        def nonlocal_assign(val):
            nonlocal dismissed_val
            dismissed_val = val

        # Option 0: conversation
        mock_event = MagicMock(spec=OptionList.OptionSelected)
        mock_event.option_index = 0
        screen.on_option_list_option_selected(mock_event)
        self.assertEqual(dismissed_val.index, 0)
        self.assertFalse(dismissed_val.restore_code)

        # Option 1: both
        dismissed_val = None
        mock_event.option_index = 1
        screen.on_option_list_option_selected(mock_event)
        self.assertEqual(dismissed_val.index, 0)
        self.assertTrue(dismissed_val.restore_code)

        # Option 2: diff pushes DiffScreen
        mock_app = MagicMock()
        mock_event.option_index = 2
        with unittest.mock.patch.object(RewindActionScreen, "app", new=mock_app):
            screen.on_option_list_option_selected(mock_event)
            mock_app.push_screen.assert_called_once()

        # Action cancel dismisses with None
        dismissed_val = "sentinel"
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

    def test_format_rewind_files(self):
        from widgets.presentation.screens.rewind import format_rewind_files

        # Empty files
        self.assertEqual(format_rewind_files([]).plain, "")

        # Files <= max_show with git stats
        res = format_rewind_files(["a.py", "b.py"], git_stats="+2/-1")
        plain = res.plain
        self.assertEqual(plain, "Files to revert (+2/-1):\n  a.py\n  b.py")

        # Files > max_show
        res = format_rewind_files(["1.py", "2.py", "3.py", "4.py", "5.py"], max_show=4)
        plain = res.plain
        self.assertEqual(plain, "Files to revert:\n  1.py\n  2.py\n  3.py\n  4.py\n  ... and 1 more")

    def test_rewind_screen_search_filtering(self):
        user_messages = [
            RewindEntry(0, "refactor database client", "+10 / -5"),
            RewindEntry(1, "fix authentication bug", "+2 / -1"),
            RewindEntry(2, "update documentation", "no changes"),
        ]
        screen = RewindScreen(user_messages, checkpoints_enabled=True)
        self.assertEqual(len(screen.filtered_entries), 3)

        screen._apply_filter("database")
        self.assertEqual(len(screen.filtered_entries), 1)
        self.assertEqual(screen.filtered_entries[0].index, 0)

        screen._apply_filter("auth")
        self.assertEqual(len(screen.filtered_entries), 1)
        self.assertEqual(screen.filtered_entries[0].index, 1)

        screen._apply_filter("")
        self.assertEqual(len(screen.filtered_entries), 3)

    async def test_rewind_screen_default_highlight(self):
        from textual.app import App

        class MockApp(App):
            pass

        app = MockApp()
        async with app.run_test() as pilot:
            user_messages = [
                RewindEntry(0, "first message"),
                RewindEntry(1, "second message"),
                RewindEntry(2, "third message"),
            ]
            screen = RewindScreen(user_messages, checkpoints_enabled=False)
            await app.push_screen(screen)
            await pilot.pause()
            opt_list = screen.query_one(OptionList)
            self.assertEqual(opt_list.highlighted, 3)
            self.assertEqual(screen.filtered_items[opt_list.highlighted], -1)

    async def test_rewind_screen_arrow_key_navigation(self):
        from textual.app import App

        class MockApp(App):
            pass

        app = MockApp()
        async with app.run_test() as pilot:
            user_messages = [
                RewindEntry(0, "first message"),
                RewindEntry(1, "second message"),
                RewindEntry(2, "third message"),
            ]
            screen = RewindScreen(user_messages, checkpoints_enabled=False)
            await app.push_screen(screen)
            await pilot.pause()

            opt_list = screen.query_one(OptionList)
            self.assertEqual(opt_list.highlighted, 3)

            # Press up arrow while focus is in search input
            await pilot.press("up")
            await pilot.pause()
            self.assertEqual(opt_list.highlighted, 2)

            # Press up again
            await pilot.press("up")
            await pilot.pause()
            self.assertEqual(opt_list.highlighted, 1)

            # Press down arrow
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(opt_list.highlighted, 2)


