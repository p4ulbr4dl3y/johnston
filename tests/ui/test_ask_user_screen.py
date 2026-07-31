import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from textual.app import App, ComposeResult
from textual.events import Focus, Key
from textual.widgets import Input, OptionList

from widgets.screens.ask_user import (
    AskUserWizardScreen,
    ConfirmScreen,
    QuestionScreen,
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
            inp.select_all()
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


class TestQuestionScreenUnit(unittest.TestCase):
    def test_init_and_bindings(self):
        qs = QuestionScreen("1/1", "Question?", ["A", "B"], current_val="A")
        self.assertEqual(qs.num_text, "1/1")
        self.assertEqual(qs.question_text, "Question?")
        self.assertEqual(qs.raw_options, ["A", "B"])
        self.assertEqual(qs.options, ["A", "B", "Write-in..."])
        self.assertEqual(qs.current_val, "A")

    def test_action_cancel(self):
        qs = QuestionScreen("1/1", "Q?", ["A"])
        qs.dismiss = MagicMock()
        qs.action_cancel()
        qs.dismiss.assert_called_once_with({"status": "cancelled", "answer": "Cancelled"})

    def test_action_quit(self):
        qs = QuestionScreen("1/1", "Q?", ["A"])
        mock_app = MagicMock()
        with patch.object(QuestionScreen, "app", new_callable=PropertyMock, return_value=mock_app):
            qs.action_quit()
            mock_app.exit.assert_called_once()

    def test_on_key_shift_tab(self):
        qs = QuestionScreen("1/1", "Q?", ["A"])
        event = Key("shift+tab", "shift+tab")
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        qs._on_key(event)
        event.prevent_default.assert_called_once()
        event.stop.assert_called_once()

    def test_submit_answer_exception_handling(self):
        qs = QuestionScreen("1/1", "Q?", ["A"])
        qs.query_one = MagicMock(side_effect=Exception("Widget missing"))
        qs.dismiss = MagicMock()
        qs.submit_answer()
        qs.dismiss.assert_called_once_with({"status": "error", "answer": "Error: Widget missing"})

    def test_question_screen_focus_and_events(self):
        qs = QuestionScreen("1/1", "Q?", ["A", "B"])
        qs._mount_time = 0.0
        qs.dismiss = MagicMock()

        # Exception handling in focus_write_in_input & focus_options_list
        qs.query_one = MagicMock(side_effect=Exception("query fail"))
        qs.focus_write_in_input()
        qs.focus_options_list()

        # focus_options_list with raw_options
        mock_input = MagicMock()
        mock_opt = MagicMock()
        qs.query_one = MagicMock(side_effect=lambda selector, *args: mock_input if "write-in" in selector else mock_opt)
        qs.focus_options_list()
        self.assertFalse(mock_input.display)
        mock_opt.focus.assert_called_once()

        # on_option_list_option_highlighted Write-in vs normal
        qs._is_mounted = True
        qs.focus_write_in_input = MagicMock()
        mock_option = MagicMock()
        mock_option.id = "opt_1"
        event_last = OptionList.OptionHighlighted(mock_opt, mock_option, 2)
        event_last.option_index = 2
        qs.on_option_list_option_highlighted(event_last)
        qs.focus_write_in_input.assert_called_once()

        event_first = OptionList.OptionHighlighted(mock_opt, mock_option, 0)
        event_first.option_index = 0
        qs.on_option_list_option_highlighted(event_first)
        self.assertFalse(mock_input.display)

        # on_option_list_option_selected
        qs.submit_answer = MagicMock()
        qs.on_option_list_option_selected(event_first)
        qs.submit_answer.assert_called_once()

        qs.submit_answer.reset_mock()
        qs.focus_write_in_input.reset_mock()
        qs.on_option_list_option_selected(event_last)
        qs.focus_write_in_input.assert_called_once()

        # action_go_next and on_key
        qs.action_go_next()
        qs.submit_answer.assert_called_once_with(status="next")

        event_up = Key("up", "up")
        event_up.prevent_default = MagicMock()
        event_up.stop = MagicMock()
        qs.focus_options_list = MagicMock()
        qs.on_key(event_up)
        qs.focus_options_list.assert_called_once()


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

    async def test_question_screen_pilot_options_select(self):
        screen = QuestionScreen("Q 1/1", "Select option", ["Option A", "Option B"], current_val="Option A")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.dismiss_result, {"status": "next", "answer": "Option A"})

    async def test_question_screen_pilot_custom_write_in(self):
        screen = QuestionScreen("Q 1/1", "Select option", ["Option A", "Option B"], current_val="Custom text")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            input_field = screen.query_one("#write-in-input", Input)
            self.assertEqual(input_field.value, "Custom text")

            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.dismiss_result, {"status": "next", "answer": "Custom text"})

    async def test_question_screen_pilot_no_options(self):
        screen = QuestionScreen("Q 1/1", "Type custom answer", [])
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            await pilot.press("h", "e", "l", "l", "o")
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.dismiss_result, {"status": "next", "answer": "hello"})

    async def test_question_screen_pilot_cancel_and_navigation(self):
        screen = QuestionScreen("Q 1/1", "Question", ["Opt 1", "Opt 2"])
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            await pilot.press("left")
            await pilot.pause()
            self.assertEqual(app.dismiss_result, {"status": "back", "answer": ""})

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
