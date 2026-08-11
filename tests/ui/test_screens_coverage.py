"""Coverage-focused tests for widgets/screens/mcp.py and widgets/screens/base_selection.py.

These tests exercise uncovered branches (exception paths, alternate display states,
key handlers, and selection handlers) using a mounted host app with mocked
query_one / event objects, matching the mocking style in tests/ui/test_screens_pilot.py.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App
from textual.events import Key

from widgets.screens.base_selection import BaseSelectionScreen
from widgets.screens.mcp import MCPScreen


class RaisingList(list):
    """List whose .index() always raises, but membership still works."""

    def index(self, *args, **kwargs):
        raise ValueError("boom")


class CoverageHostApp(App[None]):
    """Host app providing refresh_status_footer for testing modal screens."""

    def __init__(self, screen):
        super().__init__()
        self.screen_to_test = screen
        self.dismiss_result = None

    def on_mount(self) -> None:
        self.push_screen(self.screen_to_test)

    def refresh_status_footer(self):
        pass


async def run_mounted(screen, test):
    """Enter a host app run that mounts `screen`, run `test(screen)`, then yield."""
    app = CoverageHostApp(screen)
    async with app.run_test() as pilot:
        # pause to let on_mount / warmup complete
        await pilot.pause()
        await pilot.pause()
        test(screen)
        await pilot.pause()


class TestMCPScreenCoverage(unittest.IsolatedAsyncioTestCase):
    def _make_screen(self, mgr):
        with patch("widgets.screens.mcp.get_mcp_manager") as mock_get:
            mock_get.return_value = mgr
            return MCPScreen()

    async def test_action_quit_app(self):
        mgr = MagicMock()
        screen = self._make_screen(mgr)
        mgr.load_servers.return_value = []
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            with patch.object(screen.app, "exit") as mock_exit:
                screen.action_quit_app()
                mock_exit.assert_called_once()

    async def test_refresh_list_all_statuses(self):
        servers = [
            {"name": "disc", "command": "x", "disabled": True, "scope": "global"},
            {"name": "tsrv", "command": "py", "disabled": False, "scope": "global"},
            {"name": "urlsrv", "url": "http://host", "disabled": False, "scope": "global"},
            {"name": "sfail", "command": "x", "disabled": False, "scope": "global"},
            {"name": "tmo", "command": "x", "disabled": False, "scope": "global"},
            {"name": "ambi", "command": "x", "url": "http://u", "disabled": False, "scope": "global"},
            {"name": "nocmd", "disabled": False, "scope": "global"},
        ]
        client_with_tools = MagicMock()
        client_with_tools.tools = [{"name": "t1"}, {"name": "t2"}]
        client_with_tools.last_error = None
        client_sfail = MagicMock()
        client_sfail.tools = []
        client_sfail.last_error = "Process start failed: boom"
        client_tmo = MagicMock()
        client_tmo.tools = []
        client_tmo.last_error = "request timeout"

        mgr = MagicMock()
        mgr.load_servers.return_value = servers
        mgr.clients = {
            "tsrv": client_with_tools,
            "sfail": client_sfail,
            "tmo": client_tmo,
        }

        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            opt_list = MagicMock()
            opt_list.highlighted = None
            screen.query_one = MagicMock(return_value=opt_list)
            screen.refresh_list()
            calls = [str(c.args[0]) for c in opt_list.add_option.call_args_list]
            joined = "\n".join(calls)
            self.assertIn("OFF", joined)
            self.assertIn("2 tools", joined)
            self.assertIn("URL unsupported", joined)
            self.assertIn("Start failed", joined)
            self.assertIn("Timeout", joined)
            self.assertIn("[ON]", joined)
            self.assertEqual(opt_list.highlighted, 0)

    async def test_refresh_list_no_servers(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = []
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            opt_list = MagicMock()
            screen.query_one = MagicMock(return_value=opt_list)
            screen.refresh_list()
            self.assertEqual(screen.filtered_servers, [])
            text = str(opt_list.add_option.call_args.args[0])
            self.assertIn("No MCP servers", text)

    async def test_refresh_list_filter_with_prev_highlight(self):
        servers = [
            {"name": "alpha", "command": "py", "disabled": False, "scope": "global"},
            {"name": "beta", "command": "py", "disabled": False, "scope": "global"},
        ]
        mgr = MagicMock()
        mgr.load_servers.return_value = servers
        mgr.clients = {}
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            opt_list = MagicMock()
            opt_list.highlighted = 1
            screen.query_one = MagicMock(return_value=opt_list)
            screen.search_query = "alpha"
            screen.refresh_list()
            self.assertEqual(len(screen.filtered_servers), 1)
            self.assertEqual(opt_list.highlighted, 1)

    async def test_on_mount_focus_exception(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = []
        screen = self._make_screen(mgr)
        opt_list = MagicMock()
        opt_list.highlighted = None

        def fake_qo(id_, *args):
            if "search-input" in id_:
                raise Exception("no input")
            return opt_list

        screen.query_one = MagicMock(side_effect=fake_qo)
        # Patch _warmup_tools to an AsyncMock so the on_mount create_task call
        # schedules a mock coroutine instead of a real one (avoids an unraised
        # "coroutine never awaited" warning when the test finishes).
        screen._warmup_tools = AsyncMock()
        with patch("widgets.screens.mcp.asyncio.create_task", return_value=MagicMock()):
            screen.on_mount()

    async def test_warmup_tools_success_mounted(self):
        mgr = MagicMock()
        mgr.get_active_tools.return_value = []
        screen = self._make_screen(mgr)
        screen.refresh_list = MagicMock()
        screen.refresh_list.reset_mock()
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.refresh_list.reset_mock()
            await screen._warmup_tools()
            screen.refresh_list.assert_called()

    async def test_warmup_tools_not_mounted_skips_refresh(self):
        mgr = MagicMock()
        mgr.get_active_tools.return_value = []
        screen = self._make_screen(mgr)
        screen.refresh_list = MagicMock()
        # Not mounted -> is_mounted getter False
        await screen._warmup_tools()
        screen.refresh_list.assert_not_called()

    async def test_warmup_tools_exception(self):
        mgr = MagicMock()
        mgr.get_active_tools.side_effect = Exception("boom")
        screen = self._make_screen(mgr)
        screen.refresh_list = MagicMock()
        await screen._warmup_tools()
        screen.refresh_list.assert_not_called()

    async def test_on_input_changed(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = [
            {"name": "srv", "command": "py", "disabled": False, "scope": "global"}
        ]
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            opt_list = MagicMock()
            opt_list.highlighted = None
            screen.query_one = MagicMock(return_value=opt_list)
            event = MagicMock()
            event.input.id = "modal-search-input"
            event.value = "srv"
            screen.on_input_changed(event)
            self.assertEqual(screen.search_query, "srv")

    async def test_on_input_changed_other_input(self):
        mgr = MagicMock()
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.query_one = MagicMock()
            event = MagicMock()
            event.input.id = "other"
            screen.on_input_changed(event)
            self.assertEqual(screen.search_query, "")

    async def test_on_input_submitted(self):
        mgr = MagicMock()
        mgr.toggle_server.return_value = True
        mgr.load_servers.return_value = []
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.filtered_servers = [{"name": "srv", "disabled": False}]
            opt_list = MagicMock()
            opt_list.highlighted = 0
            screen.query_one = MagicMock(return_value=opt_list)
            event = MagicMock()
            event.input.id = "modal-search-input"
            screen.on_input_submitted(event)
            mgr.toggle_server.assert_called_once_with("srv")

    async def test_on_option_selected(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = []
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.filtered_servers = [{"name": "srv", "disabled": False}]
            opt_list = MagicMock()
            screen.query_one = MagicMock(return_value=opt_list)
            event = MagicMock()
            event.option_index = 0
            screen.on_option_list_option_selected(event)
            mgr.toggle_server.assert_called_once_with("srv")
            self.assertEqual(opt_list.highlighted, 0)

    async def test_on_option_selected_invalid_index(self):
        mgr = MagicMock()
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.filtered_servers = [{"name": "srv"}]
            screen.query_one = MagicMock(return_value=MagicMock())
            event = MagicMock()
            event.option_index = 99
            screen.on_option_list_option_selected(event)
            mgr.toggle_server.assert_not_called()

    def _setup_key_harness(self, screen, highlighted=None, empty_filtered=False):
        screen.filtered_servers = [] if empty_filtered else [{"name": "srv"}]
        opt_list = MagicMock()
        opt_list.highlighted = highlighted
        search_input = MagicMock()
        search_input.has_focus = True

        def fake_qo(id_, *args):
            if "search-input" in id_:
                return search_input
            return opt_list

        screen.query_one = MagicMock(side_effect=fake_qo)
        return opt_list, search_input

    async def test_on_key_down_no_highlight(self):
        mgr = MagicMock()
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            opt_list, _ = self._setup_key_harness(screen, highlighted=None)
            event = Key(key="down", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            self.assertEqual(opt_list.highlighted, 0)
            event.prevent_default.assert_called()
            event.stop.assert_called()

    async def test_on_key_down_with_highlight(self):
        mgr = MagicMock()
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            opt_list, _ = self._setup_key_harness(screen, highlighted=1)
            event = Key(key="down", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            opt_list.action_cursor_down.assert_called_once()
            event.prevent_default.assert_called()

    async def test_on_key_up(self):
        mgr = MagicMock()
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            opt_list, _ = self._setup_key_harness(screen, highlighted=1)
            event = Key(key="up", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            opt_list.action_cursor_up.assert_called_once()

    async def test_on_key_empty_filtered(self):
        mgr = MagicMock()
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            opt_list, _ = self._setup_key_harness(screen, highlighted=None, empty_filtered=True)
            event = Key(key="down", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            self.assertIsNone(opt_list.highlighted)
            event.prevent_default.assert_called()

    async def test_on_key_exception(self):
        mgr = MagicMock()
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.query_one = MagicMock(side_effect=Exception("boom"))
            event = Key(key="down", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)  # must not raise

    async def test_on_key_ignored_keys(self):
        mgr = MagicMock()
        screen = self._make_screen(mgr)
        async with CoverageHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.query_one = MagicMock()
            event = Key(key="a", character="a")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            event.prevent_default.assert_not_called()
            event.stop.assert_not_called()


class TestBaseSelectionCoverage(unittest.IsolatedAsyncioTestCase):
    def test_on_mount_index_exception(self):
        items = RaisingList(["a", "b"])
        screen = BaseSelectionScreen("t", ["A"], items, "b", show_search=False)
        opt_list = MagicMock()
        opt_list.highlighted = None
        screen.query_one = MagicMock(return_value=opt_list)
        screen.on_mount()
        self.assertIsNone(opt_list.highlighted)
        opt_list.focus.assert_called_once()

    def test_on_mount_scroll_exception(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "b", show_search=False)
        opt_list = MagicMock()
        opt_list.highlighted = 1
        opt_list.scroll_to_highlight = MagicMock(side_effect=Exception("boom"))
        screen.query_one = MagicMock(return_value=opt_list)
        screen.on_mount()
        opt_list.focus.assert_called_once()

    def _on_input(self, screen, value):
        opt_list = MagicMock()
        screen.query_one = MagicMock(return_value=opt_list)
        event = MagicMock()
        event.value = value
        screen.on_input_changed(event)
        return opt_list

    def test_on_input_changed_section_filter_and_empty_header(self):
        options = ["Hdr1", "MatchOp", "Hdr2", "x", ""]
        items = [None, "match1", None, "z", None]
        screen = BaseSelectionScreen("t", options, items, "zzz", show_search=True)
        self._on_input(screen, "match")
        self.assertEqual(screen.filtered_items, [None, "match1"])

    def test_on_input_changed_empty_query(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "a", show_search=True)
        self._on_input(screen, "  ")
        self.assertEqual(screen.filtered_items, ["a", "b"])
        self.assertEqual(screen.filtered_options, ["A", "B"])

    def test_on_input_submitted_highlighted_item(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=False)
        opt_list = MagicMock()
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_input_submitted(MagicMock())
            mock_dismiss.assert_called_once_with("a")

    def test_on_input_submitted_highlighted_none_item_loop(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=False)
        screen.filtered_items = [None, "a"]
        opt_list = MagicMock()
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_input_submitted(MagicMock())
            mock_dismiss.assert_called_once_with("a")

    def test_on_input_submitted_all_none_default(self):
        screen = BaseSelectionScreen("t", ["A"], [None], "def", show_search=False)
        screen.filtered_items = [None]
        opt_list = MagicMock()
        opt_list.highlighted = None
        screen.query_one = MagicMock(return_value=opt_list)
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_input_submitted(MagicMock())
            mock_dismiss.assert_called_once_with("def")

    def test_on_input_submitted_no_highlight_fallback(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=False)
        opt_list = MagicMock()
        opt_list.highlighted = None
        screen.query_one = MagicMock(return_value=opt_list)
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_input_submitted(MagicMock())
            mock_dismiss.assert_called_once_with("a")

    def _base_key_harness(self, screen, highlighted=None, non_none_first=True, search_focus=True):
        items = ["a", "b"] if non_none_first else [None, "b"]
        screen.filtered_items = items
        opt_list = MagicMock()
        opt_list.highlighted = highlighted
        search_input = MagicMock()
        search_input.has_focus = search_focus

        def qo(id_, *args):
            if "search-input" in id_:
                return search_input
            return opt_list

        screen.query_one = MagicMock(side_effect=qo)
        return opt_list

    def test_on_key_down_no_highlight_picks_first(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "a", show_search=True)
        self._base_key_harness(screen, highlighted=None)
        event = Key(key="down", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)
        self.assertEqual(screen.query_one("o").highlighted, 0)
        event.prevent_default.assert_called()
        event.stop.assert_called()

    def test_on_key_down_skips_none(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "a", show_search=True)
        opt_list = self._base_key_harness(screen, highlighted=None, non_none_first=False)
        event = Key(key="down", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)
        self.assertEqual(opt_list.highlighted, 1)
        event.prevent_default.assert_called()

    def test_on_key_down_moves(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "a", show_search=True)
        opt_list = self._base_key_harness(screen, highlighted=0)
        event = Key(key="down", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)
        opt_list.action_cursor_down.assert_called_once()
        event.prevent_default.assert_called()

    def test_on_key_up_moves(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "a", show_search=True)
        opt_list = self._base_key_harness(screen, highlighted=1)
        event = Key(key="up", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)
        opt_list.action_cursor_up.assert_called_once()

    def test_on_key_search_not_focused(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=True)
        self._base_key_harness(screen, highlighted=0, search_focus=False)
        event = Key(key="down", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)
        event.prevent_default.assert_not_called()

    def test_on_key_exception(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=True)
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        event = Key(key="down", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)  # must not raise

    def test_on_option_selected_none_item_stops(self):
        screen = BaseSelectionScreen("t", ["A"], [None], "a", show_search=False)
        screen.filtered_items = [None]
        event = MagicMock()
        event.option_index = 0
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_option_list_option_selected(event)
            mock_dismiss.assert_not_called()
        event.stop.assert_called_once()

    def test_on_option_selected_item(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=False)
        screen.filtered_items = ["a"]
        event = MagicMock()
        event.option_index = 0
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_option_list_option_selected(event)
            mock_dismiss.assert_called_once_with("a")

    def test_on_option_selected_invalid_index(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=False)
        screen.filtered_items = ["a"]
        event = MagicMock()
        event.option_index = 99
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_option_list_option_selected(event)
            mock_dismiss.assert_not_called()
        event.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
