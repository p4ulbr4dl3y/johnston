import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from textual.app import App, ComposeResult
from textual.events import Focus, Key
from textual.widgets import Markdown, OptionList

from widgets.presentation.screens.ask_user import (
    AskUserWizardScreen,
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

    async def test_on_key_down_with_options(self):
        inp = WriteInInput()
        app = DummyWidgetApp(inp)
        async with app.run_test():
            inp.value = "test"
            mock_screen = MagicMock()
            mock_screen.raw_options = ["opt1", "opt2"]
            mock_screen.focus_first_option = MagicMock()

            event = Key("down", "down")
            event.stop = MagicMock()
            event.prevent_default = MagicMock()

            with patch.object(WriteInInput, "screen", new_callable=PropertyMock, return_value=mock_screen):
                await inp._on_key(event)
                mock_screen.focus_first_option.assert_called_once()
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


class TestAskUserWizardScreenUnit(unittest.TestCase):
    def test_wizard_screen_basic(self):
        questions = [{"question": "Q1", "options": ["A", "B"]}, {"question": "Q2", "options": []}]
        ws = AskUserWizardScreen(questions)
        ws._mount_time = 0.0

        # Focus methods exception handling when not mounted
        ws.query_one = MagicMock(side_effect=Exception("query fail"))
        ws.focus_write_in_input()
        ws.focus_options_list()
        ws.focus_first_option()


        # _on_key shift+tab
        event_tab = Key("shift+tab", "shift+tab")
        event_tab.prevent_default = MagicMock()
        event_tab.stop = MagicMock()
        ws._on_key(event_tab)
        event_tab.prevent_default.assert_called_once()


class TestAskUserScreensPilot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    async def test_wizard_screen_pilot_navigation_and_cancel(self):
        questions = [{"question": "Q1", "options": ["A", "B"]}, {"question": "Q2", "options": ["X", "Y"]}]
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

    async def test_wizard_new_question_highlights_first_option(self):
        questions = [
            {"question": "Q1", "options": ["A", "B", "C"]},
            {"question": "Q2", "options": ["X", "Y", "Z"]},
        ]
        screen = AskUserWizardScreen(questions)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            opt_list = screen.query_one("#options-list", OptionList)
            opt_list.highlighted = 2  # move away from first in Q1
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(screen.q_idx, 1)
            # no state for Q2 -> highlight resets to first option
            self.assertEqual(opt_list.highlighted, 0)

    async def test_wizard_go_back_restores_previous_highlight(self):
        questions = [
            {"question": "Q1", "options": ["A", "B", "C"]},
            {"question": "Q2", "options": ["X", "Y", "Z"]},
        ]
        screen = AskUserWizardScreen(questions)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            opt_list = screen.query_one("#options-list", OptionList)
            opt_list.highlighted = 2  # pick "C" in Q1
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(screen.q_idx, 1)

            await pilot.press("left")  # back to Q1
            await pilot.pause()

            self.assertEqual(screen.q_idx, 0)
            # state exists -> highlight restored to the chosen option
            self.assertEqual(opt_list.highlighted, 2)

    async def test_wizard_confirm_summary_class_applied_and_removed(self):
        questions = [
            {"question": "Q1", "options": ["A", "B"]},
            {"question": "Q2", "options": ["X", "Y"]},
        ]
        screen = AskUserWizardScreen(questions)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            md = screen.query_one("#wizard-title", Markdown)
            self.assertFalse(md.has_class("confirm-summary"))

            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # on the confirm step the class is set
            self.assertTrue(md.has_class("confirm-summary"))

            await pilot.press("left")  # back to Q2
            await pilot.pause()
            self.assertFalse(md.has_class("confirm-summary"))

    async def test_wizard_right_arrow_navigates_without_selecting(self):
        questions = [
            {"question": "Q1", "options": ["A", "B"]},
            {"question": "Q2", "options": ["X", "Y"]},
            {"question": "Q3", "options": ["M", "N"]},
        ]
        screen = AskUserWizardScreen(questions)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(screen.q_idx, 1)
            self.assertEqual(screen.answers, {})  # no answer recorded

            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(screen.q_idx, 2)

            # on the last question right shows the summary
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(screen.q_idx, 3)

            # enter still selects and moves on (to confirm)
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(screen.q_idx, 3)

    async def test_wizard_screen_with_dict_options_pilot(self):
        from widgets.presentation.screens.ask_user import format_wizard_option

        formatted = format_wizard_option(
            r"\[ ]",
            "Clean Schema (Recommended)",
            description="Refactor BaseTool params",
            width=50,
        )
        self.assertIn("Clean Schema", formatted)
        self.assertIn("[dim]Refactor BaseTool params[/dim]", formatted)
        self.assertIn("[dim italic](Recommended)[/dim italic]", formatted)

        questions = [
            {
                "question": "Which architecture?",
                "header": "Architecture",
                "options": [
                    {"label": "Approach A", "description": "Fast and light"},
                    {"label": "Approach B", "description": "Extensible and modular"},
                ],
            }
        ]
        screen = AskUserWizardScreen(questions)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            await pilot.pause()

            title_md = screen.query_one("#wizard-title", Markdown)
            self.assertIn("`Architecture`", title_md._markdown)

            # Select first option (Approach A)
            await pilot.press("enter")
            await pilot.pause()

            # Confirm step
            await pilot.press("enter")
            await pilot.pause()

            self.assertIn("Approach A", str(app.dismiss_result))


if __name__ == "__main__":
    unittest.main()

