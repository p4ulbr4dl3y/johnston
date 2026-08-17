"""Edge-case tests for widgets/command_suggestions.py (bug-hunting round)."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App, ComposeResult

from widgets.command_suggestions import CommandSuggestions


class DummySuggApp(App[None]):
    def __init__(self, sugg):
        super().__init__()
        self.sugg = sugg

    def compose(self) -> ComposeResult:
        yield self.sugg


class TestUpdateQueryCommand(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._sugg = CommandSuggestions()

    async def test_empty_text_clears(self):
        res = await self._sugg.update_query("")
        self.assertEqual(res, [])
        self.assertFalse(self._sugg.display)
        self.assertIsNone(self._sugg.mode)

    async def test_whitespace_only_no_crash(self):
        await self._sugg.update_query("   ")
        self.assertFalse(self._sugg.display)

    async def test_slash_matching_is_case_insensitive(self):
        res = await self._sugg.update_query("/HELP")
        self.assertTrue(any(c.lower() == "/help" for c in res))

    async def test_no_command_matches_hides(self):
        res = await self._sugg.update_query("/zzznotacommand")
        self.assertEqual(res, [])
        self.assertFalse(self._sugg.display)

    async def test_at_at_middle_of_word_ignored(self):
        await self._sugg.update_query("foo@bar")
        self.assertFalse(self._sugg.display)

    async def test_multiline_input_other_line_does_not_match(self):
        # A slash suggestion belongs to the current cursor line only; specifying
        # a current_line without an active "/" must not surface matches.
        res = await self._sugg.update_query("/he\nsecond line", "second line", cursor_col=11)
        self.assertEqual(res, [])

    async def test_multiline_cursor_line_with_slash_matches(self):
        # cursor is on the line that contains "/he" within a multiline input
        res = await self._sugg.update_query("first line\n/he second", "/he second", cursor_col=3)
        self.assertTrue(any(c.lower() == "/help" for c in res))


class TestUpdateQueryDedupFiles(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sugg = CommandSuggestions()

    async def test_file_query_empty_returns_all(self):
        with patch.object(self.sugg, "get_workspace_files", new=AsyncMock(return_value=["a.py", "b.py"])):
            res = await self.sugg.update_query("@", "@", 1)
        self.assertEqual(set(res), {"a.py", "b.py"})
        self.assertTrue(self.sugg.display)

    async def test_file_query_substring_match(self):
        with patch.object(self.sugg, "get_workspace_files", new=AsyncMock(return_value=["main.py", "util.py"])):
            res = await self.sugg.update_query("@ain", "@ain", 4)
        self.assertEqual(res, ["main.py"])

    async def test_file_query_case_insensitive(self):
        with patch.object(self.sugg, "get_workspace_files", new=AsyncMock(return_value=["README.md"])):
            res = await self.sugg.update_query("@read", "@read", 5)
        self.assertEqual(res, ["README.md"])

    async def test_file_dedup_no_duplicate_options(self):
        with patch.object(
            self.sugg, "get_workspace_files", new=AsyncMock(return_value=["x.py", "x.py", "x.py"])
        ):
            await self.sugg.update_query("@x", "@x", 2)
            texts = [o.prompt for o in self.sugg.options]
            self.assertEqual(len(texts), len(set(texts)))

    async def test_file_no_match_hides(self):
        with patch.object(self.sugg, "get_workspace_files", new=AsyncMock(return_value=["main.py"])):
            res = await self.sugg.update_query("@qqq", "@qqq", 4)
        self.assertEqual(res, [])
        self.assertFalse(self.sugg.display)


class TestOnOptionListOptionSelected(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sugg = CommandSuggestions()
        self.app = DummySuggApp(self.sugg)

    async def _mounted(self):
        self._ctx = self.app.run_test()
        await self._ctx.__aenter__()

    async def asyncTearDown(self):
        await self._ctx.__aexit__(None, None, None)

    async def test_mouse_select_out_of_range_ignored(self):
        await self._mounted()
        self.sugg.current_matched = ["/help"]
        self.sugg.highlighted = 5
        event = MagicMock()
        self.sugg.on_option_list_option_selected(event)
        event.stop.assert_called_once()

    async def test_mouse_select_no_current_matched_returns(self):
        await self._mounted()
        self.sugg.current_matched = []
        event = MagicMock()
        self.sugg.on_option_list_option_selected(event)
        event.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
