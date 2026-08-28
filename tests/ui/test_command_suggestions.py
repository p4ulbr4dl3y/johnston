import os
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

    async def test_bare_slash_excludes_aliases_and_preserves_priority(self):
        res = await self._sugg.update_query("/")
        self.assertTrue(len(res) > 0)
        # Primary commands must be present
        self.assertIn("/models", res)
        self.assertIn("/new", res)
        # Top of list must start with high-priority primary command, not aliases or /theme
        self.assertEqual(res[0], "/models")
        # Aliases must NOT be present in bare "/" suggestions
        self.assertNotIn("/model", res)
        self.assertNotIn("/clear", res)
        self.assertNotIn("/themes", res)
        self.assertNotIn("/color", res)

    async def test_prefix_query_includes_matching_aliases(self):
        res = await self._sugg.update_query("/cle")
        self.assertIn("/clear", res)

    async def test_prefix_query_prioritizes_primary_over_alias(self):
        res = await self._sugg.update_query("/res")
        # /resume and /reset both start with /res; primary /resume must come first
        self.assertIn("/resume", res)
        self.assertIn("/reset", res)
        self.assertLess(res.index("/resume"), res.index("/reset"))


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


class TestCommandSuggestionsCoverage(unittest.IsolatedAsyncioTestCase):
    async def test_no_running_loop_workspace_files_sync(self):
        sugg = CommandSuggestions()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=["a.py", "b/"])):
            res = await sugg.get_workspace_files()
        self.assertEqual(res, ["a.py", "b/"])
        # cached second call
        res2 = await sugg.get_workspace_files()
        self.assertEqual(res2, ["a.py", "b/"])

    async def test_workspace_walk_capped(self):
        sugg = CommandSuggestions()
        real_walk = os.walk

        def fake_walk(cwd):
            # home/root scenario: two levels
            yield (cwd, ["dir1", "dir2", ".git"], ["a.py"])
            yield os.path.join(cwd, "dir1"), [".inside", "sub"], ["b.py", "c.py"]
            yield os.path.join(cwd, "dir1", "sub"), [], ["d.py"]

        os.walk = fake_walk
        try:
            files = sugg._load_workspace_files()
        finally:
            os.walk = real_walk
        self.assertIsInstance(files, list)

    async def test_workspace_walk_raises_swallowed(self):
        sugg = CommandSuggestions()
        real_walk = os.walk
        os.walk = lambda cwd: (_ for _ in ()).throw(Exception("boom"))
        try:
            files = sugg._load_workspace_files()
        finally:
            os.walk = real_walk
        self.assertEqual(files, [])

    async def test_file_suggestion_max_50(self):
        sugg = CommandSuggestions()
        with patch.object(
            sugg,
            "get_workspace_files",
            new=AsyncMock(return_value=[f"f{i}.py" for i in range(100)]),
        ):
            res = await sugg.update_query("@", "@", 1)
        self.assertEqual(len(res), 50)
        self.assertTrue(sugg.display)

    async def test_long_command_desc_truncated(self):
        sugg = CommandSuggestions()
        cmds = [("/test", "x" * 200)]
        with patch("widgets.command_suggestions.get_all_command_suggestions", new=AsyncMock(return_value=cmds)):
            res = await sugg.update_query("/test", "/test", 5)
        self.assertEqual(res, ["/test"])
        opt_text = str(sugg.options[0].prompt)
        self.assertLessEqual(len(opt_text.split("  ")[1]), 60)

    async def test_option_selected_command_and_file_mount(self):
        from widgets.chat_input import ChatInput

        class SuggApp(App[None]):
            def __init__(self, sugg, input_widget):
                super().__init__()
                self.sugg = sugg
                self.input_widget = input_widget

            def compose(self) -> ComposeResult:
                yield self.input_widget
                yield self.sugg

        chat_input = ChatInput(id="message-input")
        chat_input.apply_suggestion = MagicMock()
        chat_input.apply_file_suggestion = MagicMock()
        chat_input.focus = MagicMock()
        sugg = CommandSuggestions()

        async def _run(setup_state):
            app = SuggApp(sugg, chat_input)
            async with app.run_test():
                setup_state()
                sugg.on_option_list_option_selected(MagicMock())
                return sugg

        await _run(
            lambda: (
                setattr(sugg, "current_matched", ["/help"]),
                setattr(sugg, "mode", "command"),
                setattr(sugg, "at_start_idx", 0),
                sugg.add_option("/help Help about commands"),
                setattr(sugg, "highlighted", 0),
            )
        )
        chat_input.apply_suggestion.assert_called_once_with("/help", 0)

        await _run(
            lambda: (
                setattr(sugg, "current_matched", ["f.py"]),
                setattr(sugg, "mode", "file"),
                setattr(sugg, "at_start_idx", 1),
                sugg.add_option("f.py"),
                setattr(sugg, "highlighted", 0),
            )
        )
        chat_input.apply_file_suggestion.assert_called_once_with("f.py", 1)


if __name__ == "__main__":
    unittest.main()
