import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from textual.app import App, ComposeResult
from textual.events import Focus, Key

from widgets.screens.ask_user import (
    AskUserWizardScreen,
    ConfirmScreen,
    WriteInInput,
)


class DummyHostApp(App[None]):
    def __init__(self, screen_to_test):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.dismiss_result = None

    def on_mount(self) -> None:
        def callback(res=None):
            self.dismiss_result = res
        self.push_screen(self.screen_to_test, callback=callback)


class DummyWidgetApp(App[None]):
    def __init__(self, widget):
        super().__init__()
        self.test_widget = widget

    def compose(self) -> ComposeResult:
        yield self.test_widget


class TestWriteInInput(unittest.IsolatedAsyncioTestCase):
    async def test_clear_selection_and_select_all(self):
        inp = WriteInInput()
        app = DummyWidgetApp(inp)
        async with app.run_test():
            inp.value = "hello"
            inp._clear_selection()
            self.assertEqual(inp.cursor_position, 5)

    async def test_clear_selection_exception_fallback(self):
        from textual.widgets._input import Selection as RealSelection
        inp = WriteInInput()
        app = DummyWidgetApp(inp)
        async with app.run_test():
            inp.value = "test"
            call_count = 0
            def mock_selection(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise Exception("Selection failed")
                return RealSelection(*args, **kwargs)
            mock_selection.cursor = RealSelection.cursor
            with patch("textual.widgets._input.Selection", mock_selection):
                inp._clear_selection()
                self.assertEqual(inp.cursor_position, 4)

    async def test_on_focus(self):
        inp = WriteInInput()
        app = DummyWidgetApp(inp)
        async with app.run_test():
            inp.value = "abc"
            inp.call_after_refresh = MagicMock()
            event = Focus()
            inp._on_focus(event)
            self.assertEqual(inp.cursor_position, 3)
            inp.call_after_refresh.assert_called_once()

    async def test_on_key_up_with_options(self):
        inp = WriteInInput()
        app = DummyWidgetApp(inp)
        async with app.run_test():
            inp.value = "test"
            mock_screen = MagicMock()
            mock_screen.raw_options = ["opt1", "opt2"]
            mock_screen.focus_options_list = MagicMock()

            event = Key("up", "up")
            event.stop = MagicMock()
            event.prevent_default = MagicMock()

            with patch.object(WriteInInput, "screen", new_callable=PropertyMock, return_value=mock_screen):
                await inp._on_key(event)
                mock_screen.focus_options_list.assert_called_once()
                event.stop.assert_called_once()
                event.prevent_default.assert_called_once()

    async def test_on_key_up_without_options(self):
        inp = WriteInInput()
        app = DummyWidgetApp(inp)
        async with app.run_test():
            inp.value = "test"
            mock_screen = MagicMock()
            mock_screen.raw_options = []
            mock_screen.action_go_back = MagicMock()

            event = Key("up", "up")
            event.stop = MagicMock()
            event.prevent_default = MagicMock()

            with patch.object(WriteInInput, "screen", new_callable=PropertyMock, return_value=mock_screen):
                await inp._on_key(event)
                mock_screen.action_go_back.assert_called_once()
                event.stop.assert_called_once()
                event.prevent_default.assert_called_once()

    async def test_on_key_left_at_cursor_zero(self):
        inp = WriteInInput()
        app = DummyWidgetApp(inp)
        async with app.run_test():
            inp.value = "test"
            inp.cursor_position = 0
            mock_screen = MagicMock()
            mock_screen.action_go_back = MagicMock()

            event = Key("left", "left")
            event.stop = MagicMock()
            event.prevent_default = MagicMock()

            with patch.object(WriteInInput, "screen", new_callable=PropertyMock, return_value=mock_screen):
                await inp._on_key(event)
                mock_screen.action_go_back.assert_called_once()

    async def test_on_key_right_at_cursor_end(self):
        inp = WriteInInput()
        app = DummyWidgetApp(inp)
        async with app.run_test():
            inp.value = "test"
            inp.cursor_position = 4
            mock_screen = MagicMock()
            mock_screen.action_go_next = MagicMock()

            event = Key("right", "right")
            event.stop = MagicMock()
            event.prevent_default = MagicMock()

            with patch.object(WriteInInput, "screen", new_callable=PropertyMock, return_value=mock_screen):
                await inp._on_key(event)
                mock_screen.action_go_next.assert_called_once()


class TestConfirmScreenUnit(unittest.TestCase):
    def test_actions(self):
        cs = ConfirmScreen("Summary here")
        cs._mount_time = 0.0
        cs.dismiss = MagicMock()

        cs.action_confirm()
        cs.dismiss.assert_called_with("confirm")

        cs.action_go_back()
        cs.dismiss.assert_called_with("back")

        cs.action_cancel()
        cs.dismiss.assert_called_with("cancelled")

    def test_action_confirm_debounce(self):
        cs = ConfirmScreen("Summary")
        cs._mount_time = time.time()
        cs.dismiss = MagicMock()
        cs.action_confirm()
        cs.dismiss.assert_not_called()

    def test_action_quit(self):
        cs = ConfirmScreen("Summary")
        mock_app = MagicMock()
        with patch.object(ConfirmScreen, "app", new_callable=PropertyMock, return_value=mock_app):
            cs.action_quit()
            mock_app.exit.assert_called_once()


class TestAskUserWizardScreenUnit(unittest.TestCase):
    def test_wizard_screen_basic(self):
        questions = [
            {"question_text": "Q1", "options": ["A", "B"]},
            {"question_text": "Q2", "options": []}
        ]
        ws = AskUserWizardScreen(questions)
        ws._mount_time = 0.0

        # Focus methods exception handling when not mounted
        ws.query_one = MagicMock(side_effect=Exception("query fail"))
        ws.focus_write_in_input()
        ws.focus_options_list()

        # _on_key tab / shift+tab
        event_tab = Key("tab", "tab")
        event_tab.prevent_default = MagicMock()
        event_tab.stop = MagicMock()
        ws._on_key(event_tab)
        event_tab.prevent_default.assert_called_once()

        # action_quit
        mock_app = MagicMock()
        with patch.object(AskUserWizardScreen, "app", new_callable=PropertyMock, return_value=mock_app):
            ws.action_quit()
            mock_app.exit.assert_called_once()


class TestAskUserScreensPilot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    async def test_confirm_screen_pilot(self):
        screen = ConfirmScreen("Do you agree?")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.dismiss_result, "confirm")

    async def test_confirm_screen_pilot_cancel(self):
        screen = ConfirmScreen("Do you agree?")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            self.assertEqual(app.dismiss_result, "cancelled")

    async def test_wizard_screen_pilot_navigation_and_cancel(self):
        questions = [
            {"question_text": "Q1", "options": ["A", "B"]},
            {"question_text": "Q2", "options": ["X", "Y"]}
        ]
        screen = AskUserWizardScreen(questions)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(screen.q_idx, 1)

            await pilot.press("left")
            await pilot.pause()

            self.assertEqual(screen.q_idx, 0)

            await pilot.press("escape")
            await pilot.pause()

            self.assertEqual(app.dismiss_result, "Cancelled by user.")


if __name__ == "__main__":
    unittest.main()
