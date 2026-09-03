"""Gating tests for the ChatInput suggestions-update task.

Regression coverage for the performance fix: `_schedule_suggestions_update`
must only spawn a task when the input line carries an active "/" or "@"
trigger (or when a previously-open suggestions list needs clearing), instead
of spawning one task per keystroke.
"""

import unittest
from unittest.mock import AsyncMock, patch

from textual.app import App, ComposeResult

from widgets.chat_input import ChatInput
from widgets.command_suggestions import CommandSuggestions


class SuggestionGateApp(App[None]):
    """Minimal app wiring input + suggestions the way the real UI does.

    Mirrors app.tcss hiding the suggestions popup until a trigger opens it.
    """

    CSS = """
#command-suggestions {
    display: none;
}
"""

    def __init__(self, chat_input):
        super().__init__()
        self.chat_input = chat_input

    def compose(self) -> ComposeResult:
        yield CommandSuggestions(id="command-suggestions")
        yield self.chat_input


class TestHasSuggestionTrigger(unittest.TestCase):
    """Direct unit tests for _has_suggestion_trigger (pure text/cursor logic)."""

    def setUp(self):
        self.ci = ChatInput()

    def _at(self, text: str, col: int) -> bool:
        self.ci.load_text(text)
        self.ci.move_cursor((0, col))
        return self.ci._has_suggestion_trigger()

    def test_plain_text_is_not_a_trigger(self):
        self.assertFalse(self._at("hello world", 11))
        self.assertFalse(self._at("", 0))
        self.assertFalse(self._at("   ", 3))

    def test_slash_at_line_start_is_trigger(self):
        self.assertTrue(self._at("/he", 3))

    def test_slash_after_whitespace_is_trigger(self):
        self.assertTrue(self._at("do /he", 6))

    def test_slash_with_space_in_query_is_not_trigger(self):
        self.assertFalse(self._at("/he ", 4))
        self.assertFalse(self._at("do /he please", 13))

    def test_at_trigger(self):
        self.assertTrue(self._at("@app", 4))
        self.assertTrue(self._at("see @app", 8))

    def test_at_mid_word_is_not_trigger(self):
        self.assertFalse(self._at("foo@bar", 7))
        self.assertFalse(self._at("test@domain.com", 15))

    def test_shell_mode_slash_is_not_command_trigger(self):
        self.ci.is_shell_mode = True
        self.assertFalse(self._at("/home", 5))
        # @ file completion still applies in shell mode
        self.assertTrue(self._at("@app", 4))


class TestSuggestionTaskGate(unittest.IsolatedAsyncioTestCase):
    """The gate: no trigger -> no task spawn; triggers still spawn tasks."""

    async def test_typing_without_trigger_never_spawns_task(self):
        ci = ChatInput()
        app = SuggestionGateApp(ci)
        async with app.run_test() as pilot:
            with patch.object(ChatInput, "update_suggestions", new=AsyncMock()) as spy:
                await pilot.press(*list("hello world"))
                await pilot.pause()
                spy.assert_not_called()
                self.assertFalse(ci._suggestions_active)

    async def test_slash_keystroke_still_spawns_update_task(self):
        ci = ChatInput()
        app = SuggestionGateApp(ci)
        async with app.run_test() as pilot:
            with patch.object(ChatInput, "update_suggestions", new=AsyncMock()) as spy:
                # every keystroke on a trigger line spawns a task, as before
                await pilot.press("/", "h")
                await pilot.pause()
                self.assertEqual(spy.call_count, 2)
                self.assertTrue(ci._suggestions_active)

    async def test_at_keystroke_spawns_update_task(self):
        ci = ChatInput()
        app = SuggestionGateApp(ci)
        async with app.run_test() as pilot:
            with patch.object(ChatInput, "update_suggestions", new=AsyncMock()) as spy:
                # "x" and " " spawn nothing; "@" and "a" complete the trigger
                await pilot.press("x", " ", "@", "a")
                await pilot.pause()
                self.assertEqual(spy.call_count, 2)
                self.assertTrue(ci._suggestions_active)

    async def test_plain_typing_never_filters_files(self):
        ci = ChatInput()
        app = SuggestionGateApp(ci)
        async with app.run_test() as pilot:
            sugg = app.query_one(CommandSuggestions)
            with patch.object(sugg, "get_workspace_files", new=AsyncMock(return_value=[])) as files_mock:
                await pilot.press(*list("plain text"))
                await pilot.pause()
                files_mock.assert_not_awaited()
                self.assertFalse(sugg.display)

    async def test_cleared_state_does_not_respawn_without_trigger(self):
        ci = ChatInput()
        app = SuggestionGateApp(ci)
        async with app.run_test() as pilot:
            await pilot.press("/he")
            await pilot.pause()
            await pilot.press("backspace", "backspace", "backspace")
            await pilot.pause()
            with patch.object(ChatInput, "update_suggestions", new=AsyncMock()) as spy:
                await pilot.press("x", "y", "z")
                await pilot.pause()
                spy.assert_not_called()
                self.assertFalse(ci._suggestions_active)


class TestSuggestionGateEndToEnd(unittest.IsolatedAsyncioTestCase):
    """Real CommandSuggestions: triggers open the list, removal clears it."""

    async def test_slash_opens_and_removal_clears_list(self):
        ci = ChatInput()
        app = SuggestionGateApp(ci)
        async with app.run_test() as pilot:
            sugg = app.query_one(CommandSuggestions)

            await pilot.press("/", "h", "e")
            await pilot.pause()
            self.assertTrue(sugg.display)
            self.assertEqual(sugg.mode, "command")
            self.assertGreater(sugg.option_count, 0)

            await pilot.press("backspace", "backspace", "backspace")
            await pilot.pause()
            self.assertFalse(sugg.display)
            self.assertIsNone(sugg.mode)
            self.assertEqual(sugg.option_count, 0)

    async def test_at_trigger_runs_file_filtering(self):
        ci = ChatInput()
        app = SuggestionGateApp(ci)
        async with app.run_test() as pilot:
            sugg = app.query_one(CommandSuggestions)
            with patch.object(
                sugg, "get_workspace_files", new=AsyncMock(return_value=["app.py", "src/main.py"])
            ) as files_mock:
                # "@" and "a" both land on an active @ trigger -> two filter runs
                await pilot.press("x", " ", "@", "a")
                await pilot.pause()
                self.assertEqual(files_mock.await_count, 2)
                self.assertEqual(sugg.mode, "file")
                self.assertTrue(sugg.display)

    async def test_email_like_token_never_opens_file_suggestions(self):
        ci = ChatInput()
        app = SuggestionGateApp(ci)
        async with app.run_test() as pilot:
            sugg = app.query_one(CommandSuggestions)
            with patch.object(sugg, "get_workspace_files", new=AsyncMock(return_value=[])) as files_mock:
                await pilot.press(*list("test@domain.com"))
                await pilot.pause()
                files_mock.assert_not_awaited()
                self.assertFalse(sugg.display)
                self.assertIsNone(sugg.mode)


if __name__ == "__main__":
    unittest.main()
