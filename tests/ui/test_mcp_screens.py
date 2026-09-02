"""Tests for widgets/presentation/screens/mcp.py.

Consolidates the basic init/bindings checks, the render-regression suite (the
background loader must re-schedule its render off the worker thread) and the
coverage/exception-path tests for the MCP modal.
"""

import asyncio
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App
from textual.events import Key
from textual.widgets import OptionList

from widgets.presentation.screens.mcp import MCPScreen


class _MCPScreenHost(App[None]):
    """Host app providing refresh_status_footer for mounted MCP tests."""

    def __init__(self, screen_to_test=None):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.dismiss_result = None

    def on_mount(self) -> None:
        if self.screen_to_test is not None:
            self.push_screen(self.screen_to_test)

    def refresh_status_footer(self):
        pass


class _MCPToggleHost(App[None]):
    """Host app providing refresh_status_footer for _do_toggle tests."""

    def __init__(self):
        super().__init__()
        self.footer_calls = 0

    def on_mount(self):
        pass

    def refresh_status_footer(self):
        self.footer_calls += 1


async def _run_mounted(screen, test):
    """Enter a host app run that mounts `screen`, run `test(screen)`, then yield."""
    app = _MCPScreenHost(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        test(screen)
        await pilot.pause()


def _mock_mgr(servers):
    mgr = MagicMock()
    mgr.load_servers.return_value = servers
    mgr.clients = {}
    mgr.ensure_tools_ready_async = AsyncMock(return_value=[])
    mgr.warm_server_async = AsyncMock(return_value=None)
    mgr.get_server_status.return_value = {"tools": 0, "error": None, "running": False}
    return mgr


def _make_screen(mgr):
    with patch("widgets.presentation.screens.mcp.get_mcp_manager") as mock_get:
        mock_get.return_value = mgr
        return MCPScreen()


class TestMCPScreen(unittest.TestCase):
    @patch("widgets.presentation.screens.mcp.get_mcp_manager")
    def test_init(self, mock_get_mgr):
        mock_mgr = MagicMock()
        mock_mgr.load_servers.return_value = []
        mock_get_mgr.return_value = mock_mgr

        s = MCPScreen()
        self.assertEqual(s.servers, [])
        self.assertEqual(s.mm, mock_mgr)

    def test_bindings(self):
        keys = [b[0] for b in MCPScreen.BINDINGS]
        self.assertIn("escape", keys)


class TestMCPScreenRenderRegression(unittest.IsolatedAsyncioTestCase):
    """Regression: opening the MCP modal must render configured servers.

    The background loader runs in a ThreadPoolExecutor and re-schedules the
    render via call_soon_threadsafe on the captured event loop; if that
    callback is lost (e.g. get_running_loop() called inside the worker
    thread), the OptionList stays empty and the modal shows no servers.
    """

    async def _wait_until(self, cond, attempts=150):
        """Poll until the executor callback lands (loop closes at teardown)."""
        for _ in range(attempts):
            if cond():
                return True
            await asyncio.sleep(0.01)
        return False

    async def test_modal_renders_configured_servers(self):
        servers = [
            {"name": "alpha", "command": "py", "scope": "global"},
            {"name": "beta", "command": "py", "enabled": False, "scope": "global"},
            {"name": "gamma", "command": "py", "scope": "project"},
        ]
        screen = _make_screen(_mock_mgr(servers))
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            rendered = await self._wait_until(lambda: screen.filtered_servers)
            self.assertTrue(rendered, "modal never rendered any server row")
            opt_list = screen.query_one("#mcp-option-list", OptionList)
            self.assertGreater(opt_list.option_count, 0)
            names = [s["name"] for s in screen.filtered_servers if s is not None]
            self.assertEqual(names, ["alpha", "beta", "gamma"])
            # Header rows present in lockstep position
            self.assertIsNone(screen.filtered_servers[0])

    async def test_modal_empty_config_placeholder(self):
        screen = _make_screen(_mock_mgr([]))
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            rendered = await self._wait_until(
                lambda: screen.servers == [] and screen.filtered_servers == []
            )
            self.assertTrue(rendered, "placeholder row never rendered")
            opt_list = screen.query_one("#mcp-option-list", OptionList)
            self.assertGreater(opt_list.option_count, 0)
            first = opt_list.get_option_at_index(0).prompt
            self.assertIn("No MCP servers configured", str(first))

    async def test_modal_refresh_after_background_load_keeps_rows(self):
        # Modal opened before the config cache was warm: the first background
        # load lands after on_mount, and a second refresh (e.g. after warmup)
        # must not blank the list.
        servers = [
            {"name": "alpha", "command": "py", "scope": "global"},
        ]
        screen = _make_screen(_mock_mgr(servers))
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            rendered = await self._wait_until(lambda: screen.servers)
            self.assertTrue(rendered)
            screen.refresh_list()
            await self._wait_until(lambda: screen.filtered_servers)
            self.assertEqual(screen.filtered_servers[1]["name"], "alpha")

    async def test_load_servers_bg_renders_after_executor(self):
        # Cold cache: refresh_list only submitted the executor load; the modal
        # must still render once the worker thread finishes. This is the exact
        # reported bug — the async callback back onto the event loop was lost,
        # leaving the OptionList permanently empty.
        servers = [
            {"name": "alpha", "command": "py", "scope": "global"},
        ]
        screen = _make_screen(_mock_mgr(servers))
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            screen.servers = []
            screen.filtered_servers = []
            screen._load_servers_bg(refresh=True)
            rendered = await self._wait_until(lambda: screen.filtered_servers)
            self.assertTrue(rendered, "executor load never re-scheduled the render")
            self.assertEqual(screen.filtered_servers[1]["name"], "alpha")

    async def _press_spam(self, pilot, opt_list, seconds_gap=0.02):
        """Return elapsed seconds for a burst of enter presses."""
        opt_list.highlighted = 1
        start = time.monotonic()
        for _ in range(6):
            await pilot.press("enter")
            await asyncio.sleep(seconds_gap)
        return time.monotonic() - start

    async def test_enter_spam_does_not_block_ui(self):
        # Regression: toggling ran synchronously on the UI thread; a blocking
        # toggle (config write + client stop, up to seconds) froze the modal
        # on every enter. It must run off-thread with duplicate toggles for
        # the same server dropped while one is in flight.
        servers = [
            {"name": "alpha", "command": "py", "scope": "global"},
        ]

        # Baseline: measure how long a burst of 6 enters takes when the toggle
        # is instant. Compare the slow-toggle burst against this baseline so the
        # assertion scales with machine load instead of an absolute wallclock.
        baseline_mgr = _mock_mgr(list(servers))
        baseline_calls: list[str] = []
        baseline_mgr.toggle_server = lambda name: (baseline_calls.append(name), True)[1]

        baseline_screen = _make_screen(baseline_mgr)
        async with _MCPScreenHost(baseline_screen).run_test() as baseline_pilot:
            await baseline_pilot.pause()
            await self._wait_until(lambda: baseline_screen.filtered_servers)
            baseline_opt = baseline_screen.query_one("#mcp-option-list", OptionList)
            baseline_elapsed = await self._press_spam(baseline_pilot, baseline_opt)

        mgr = _mock_mgr(servers)
        calls: list[str] = []
        # Deterministic in-flight lock: the toggle blocks in a worker thread
        # until released, so it can never complete (and drop the pending guard)
        # mid-burst regardless of how slowly/paused the presses are delivered.
        release_toggle = threading.Event()

        def slow_toggle(name):
            calls.append(name)
            release_toggle.wait()
            return True

        mgr.toggle_server = slow_toggle
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            await self._wait_until(lambda: screen.filtered_servers)
            opt_list = screen.query_one("#mcp-option-list", OptionList)
            elapsed = await self._press_spam(pilot, opt_list)
            # A serial UI blocker would add ~4s per press (blocked toggles) over
            # the baseline; the off-thread path adds only a small constant, and
            # the blocked in-flight toggle keeps the duplicate guard active for
            # the whole burst (exactly one enter gets through).
            self.assertLess(elapsed, baseline_elapsed + 3.0, "enter spam blocked the UI thread")
            self.assertEqual(calls, ["alpha"])
            # Modal kept its rows while the toggle was in flight.
            self.assertTrue(screen.filtered_servers)
            # Release the in-flight toggle and wait for it to finish + re-render.
            release_toggle.set()
            await asyncio.sleep(0.3)
            await self._wait_until(lambda: not screen._pending_toggles)
            self.assertEqual(calls, ["alpha"])

    async def test_enter_after_toggle_finishes_toggles_again(self):
        # Once the in-flight toggle completes, a later enter toggles again
        # (no permanent lock on the server).
        servers = [
            {"name": "alpha", "command": "py", "scope": "global"},
        ]
        mgr = _mock_mgr(servers)
        calls: list[str] = []

        def slow_toggle(name):
            calls.append(name)
            time.sleep(0.1)
            return True

        mgr.toggle_server = slow_toggle
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            await self._wait_until(lambda: screen.filtered_servers)
            opt_list = screen.query_one("#mcp-option-list", OptionList)
            opt_list.highlighted = 1
            await pilot.press("enter")
            await self._wait_until(lambda: not screen._pending_toggles)
            await pilot.press("enter")
            await self._wait_until(lambda: not screen._pending_toggles)
            self.assertEqual(calls, ["alpha", "alpha"])

    async def test_toggle_enable_kicks_warmup_and_shows_tool_count(self):
        # Enabling a server in the modal must warm that exact server right away
        # (bypassing the manager's 30s freshness window) and refresh the row
        # with "N tools" once tools land — no reopen needed.
        servers = [
            {"name": "alpha", "command": "py", "enabled": False, "scope": "global"},
        ]
        mgr = _mock_mgr(servers)
        state = {"enabled": False}
        warm_calls = []

        def toggle(name):
            state["enabled"] = not state["enabled"]
            return state["enabled"]

        mgr.toggle_server = toggle
        mgr.load_servers = lambda: [
            {"name": "alpha", "command": "py", "enabled": state["enabled"], "scope": "global"}
        ]

        async def warm(name):
            warm_calls.append(name)
            mgr.get_server_status.return_value = {"tools": 2, "error": None, "running": True}

        mgr.warm_server_async = warm
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            await self._wait_until(lambda: screen.filtered_servers)
            opt_list = screen.query_one("#mcp-option-list", OptionList)
            opt_list.highlighted = 1
            await pilot.press("enter")
            await self._wait_until(lambda: not screen._pending_toggles)
            self.assertEqual(warm_calls, ["alpha"])
            opt_list = screen.query_one("#mcp-option-list", OptionList)
            texts = [str(opt_list.get_option_at_index(i).prompt) for i in range(opt_list.option_count)]
            self.assertTrue(any("2 tools" in t for t in texts), texts)

    async def test_toggle_enable_shows_error_badge_after_failed_start(self):
        # When the targeted warm fails (e.g. cold npx start timeout), the row
        # must show an ERR badge with the error kind instead of a bare ON.
        servers = [
            {"name": "alpha", "command": "py", "enabled": False, "scope": "global"},
        ]
        mgr = _mock_mgr(servers)
        state = {"enabled": False}

        def toggle(name):
            state["enabled"] = not state["enabled"]
            return state["enabled"]

        mgr.toggle_server = toggle
        mgr.load_servers = lambda: [
            {"name": "alpha", "command": "py", "enabled": state["enabled"], "scope": "global"}
        ]

        async def warm(name):
            mgr.get_server_status.return_value = {
                "tools": 0,
                "error": "Server start timed out after 15s",
                "running": False,
            }

        mgr.warm_server_async = warm
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            await self._wait_until(lambda: screen.filtered_servers)
            opt_list = screen.query_one("#mcp-option-list", OptionList)
            opt_list.highlighted = 1
            await pilot.press("enter")
            await self._wait_until(lambda: not screen._pending_toggles)
            opt_list = screen.query_one("#mcp-option-list", OptionList)
            texts = [str(opt_list.get_option_at_index(i).prompt) for i in range(opt_list.option_count)]
            # "▲" is the ERR status tag; "Timeout" is the mapped error badge.
            self.assertTrue(any("▲" in t and "Timeout" in t for t in texts), texts)

    async def test_modal_never_blank_while_background_load_queued(self):
        # Regression: a busy worker pool (long to_thread toggles from an
        # earlier modal) delays the background load; the modal must render the
        # placeholder row synchronously from on_mount instead of a blank box.
        servers = [
            {"name": "alpha", "command": "py", "scope": "global"},
        ]
        screen = _make_screen(_mock_mgr(servers))
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#mcp-option-list", OptionList)
            self.assertGreater(opt_list.option_count, 0)
            await self._wait_until(lambda: screen.filtered_servers)


class TestMCPScreenCoverage(unittest.IsolatedAsyncioTestCase):
    async def test_action_quit_app(self):
        mgr = MagicMock()
        screen = _make_screen(mgr)
        mgr.load_servers.return_value = []
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            with patch.object(screen.app, "exit") as mock_exit:
                screen.action_quit_app()
                mock_exit.assert_called_once()

    async def test_refresh_list_all_statuses(self):
        servers = [
            {"name": "disc", "command": "x", "enabled": False, "scope": "global"},
            {"name": "tsrv", "command": "py", "scope": "global"},
            {"name": "urlsrv", "url": "http://host", "scope": "global"},
            {"name": "sfail", "command": "x", "scope": "global"},
            {"name": "tmo", "command": "x", "scope": "global"},
            {"name": "ambi", "command": "x", "url": "http://u", "scope": "global"},
            {"name": "nocmd", "scope": "global"},
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

        def _status(name):
            c = mgr.clients.get(name)
            if c is None:
                return {"server": name, "tools": 0, "error": None, "running": False}
            return {
                "server": name,
                "tools": len(getattr(c, "tools", None) or []),
                "error": getattr(c, "last_error", None),
                "running": True,
            }

        mgr.get_server_status.side_effect = _status

        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            opt_list = MagicMock()
            opt_list.highlighted = None
            screen.query_one = MagicMock(return_value=opt_list)
            screen.refresh_list()
            calls = [str(c.args[0]) for c in opt_list.add_option.call_args_list]
            joined = "\n".join(calls)
            self.assertIn("○", joined)
            self.assertIn("2 tools", joined)
            self.assertIn("Start failed", joined)
            self.assertIn("Timeout", joined)
            self.assertIn("●", joined)
            # first selectable row is index 1 (GLOBAL header is index 0)
            self.assertEqual(opt_list.highlighted, 1)

    async def test_refresh_list_no_servers(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = []
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            opt_list = MagicMock()
            screen.query_one = MagicMock(return_value=opt_list)
            # refresh_list loads servers on an executor; emulate the completed
            # background load so the no-servers render path is exercised directly.
            screen.servers = list(mgr.load_servers.return_value)
            screen._render_from_cache()
            self.assertEqual(screen.filtered_servers, [])
            text = str(opt_list.add_option.call_args.args[0])
            self.assertIn("No MCP servers", text)

    async def test_refresh_list_filter_with_prev_highlight(self):
        servers = [
            {"name": "alpha", "command": "py", "scope": "global"},
            {"name": "beta", "command": "py", "scope": "global"},
        ]
        mgr = MagicMock()
        mgr.load_servers.return_value = servers
        mgr.clients = {}
        mgr.get_server_status.return_value = {"tools": 0}
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            opt_list = MagicMock()
            opt_list.highlighted = 1
            screen.query_one = MagicMock(return_value=opt_list)
            screen.search_query = "alpha"
            screen.refresh_list()
            # GLOBAL header (None) + alpha
            self.assertEqual(len(screen.filtered_servers), 2)
            self.assertIsNone(screen.filtered_servers[0])
            self.assertEqual(screen.filtered_servers[1]["name"], "alpha")
            self.assertEqual(opt_list.highlighted, 1)

    async def test_on_mount_focus_exception(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = []
        screen = _make_screen(mgr)
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
        with patch("widgets.presentation.screens.mcp.asyncio.create_task", return_value=MagicMock()):
            screen.on_mount()

    async def test_warmup_tools_success_mounted(self):
        mgr = MagicMock()
        mgr.ensure_tools_ready_async = AsyncMock(return_value=[])
        screen = _make_screen(mgr)
        screen.refresh_list = MagicMock()
        screen.refresh_list.reset_mock()
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            screen.refresh_list.reset_mock()
            await screen._warmup_tools()
            screen.refresh_list.assert_called()

    async def test_warmup_tools_not_mounted_skips_refresh(self):
        mgr = MagicMock()
        mgr.ensure_tools_ready_async = AsyncMock(return_value=[])
        screen = _make_screen(mgr)
        screen.refresh_list = MagicMock()
        # Not mounted -> is_mounted getter False
        await screen._warmup_tools()
        screen.refresh_list.assert_not_called()

    async def test_warmup_tools_exception(self):
        mgr = MagicMock()
        mgr.ensure_tools_ready_async = AsyncMock(side_effect=Exception("boom"))
        screen = _make_screen(mgr)
        screen.refresh_list = MagicMock()
        await screen._warmup_tools()
        screen.refresh_list.assert_not_called()

    async def test_on_input_changed(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = [
            {"name": "srv", "command": "py", "scope": "global"}
        ]
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
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
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
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
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            screen.filtered_servers = [{"name": "srv"}]
            opt_list = MagicMock()
            opt_list.highlighted = 0
            screen.query_one = MagicMock(return_value=opt_list)
            event = MagicMock()
            event.input.id = "modal-search-input"
            screen.on_input_submitted(event)
            # Toggle runs off the UI thread; give the worker time to land.
            await pilot.pause()
            await asyncio.sleep(0.05)
            mgr.toggle_server.assert_called_once_with("srv")

    async def test_on_option_selected(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = []
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            screen.filtered_servers = [{"name": "srv"}]
            opt_list = MagicMock()
            screen.query_one = MagicMock(return_value=opt_list)
            event = MagicMock()
            event.option_index = 0
            screen.on_option_list_option_selected(event)
            await pilot.pause()
            await asyncio.sleep(0.05)
            mgr.toggle_server.assert_called_once_with("srv")
            self.assertEqual(opt_list.highlighted, 0)

    async def test_on_option_selected_invalid_index(self):
        mgr = MagicMock()
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
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
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
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
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
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
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            opt_list, _ = self._setup_key_harness(screen, highlighted=1)
            event = Key(key="up", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            opt_list.action_cursor_up.assert_called_once()

    async def test_on_key_empty_filtered(self):
        mgr = MagicMock()
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
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
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            screen.query_one = MagicMock(side_effect=Exception("boom"))
            event = Key(key="down", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)  # must not raise

    async def test_on_key_ignored_keys(self):
        mgr = MagicMock()
        screen = _make_screen(mgr)
        async with _MCPScreenHost(screen).run_test() as pilot:
            await pilot.pause()
            screen.query_one = MagicMock()
            event = Key(key="a", character="a")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            event.prevent_default.assert_not_called()
            event.stop.assert_not_called()


class TestMCPScreenExtra(unittest.IsolatedAsyncioTestCase):
    def test_init_load_servers_exception(self):
        mgr = MagicMock()
        mgr.load_servers.side_effect = Exception("boom")
        with patch("widgets.presentation.screens.mcp.get_mcp_manager", return_value=mgr):
            screen = MCPScreen()
        self.assertEqual(screen.servers, [])

    def test_on_unmount_cancels(self):
        screen = MCPScreen.__new__(MCPScreen)
        wtask = MagicMock()
        wtask.done.return_value = False
        screen._warmup_task = wtask
        t = MagicMock()
        screen._toggle_tasks = {t}
        screen.on_unmount()
        wtask.cancel.assert_called_once()
        t.cancel.assert_called_once()

    async def test_warmup_tools_waits_refresh_task(self):
        mgr = MagicMock()
        mgr.ensure_tools_ready_async = AsyncMock()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        mgr._tools_refresh_task = fut
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen.refresh_list = MagicMock()
        screen._is_mounted = True
        task = asyncio.create_task(screen._warmup_tools())
        await asyncio.sleep(0.01)
        self.assertFalse(task.done())
        fut.set_result(None)
        await task
        screen.refresh_list.assert_called()

    async def test_load_servers_bg_sync_no_loop(self):
        mgr = MagicMock()
        mgr.load_servers.side_effect = Exception("boom")
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen.servers = ["cached"]
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            screen._load_servers_bg(refresh=True)
        self.assertEqual(screen.servers, ["cached"])

    async def test_load_servers_bg_call_soon_threadsafe_raises(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = [{"name": "a", "command": "x"}]
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen.servers = []
        screen._is_mounted = True
        loop = asyncio.get_running_loop()
        with patch.object(loop, "call_soon_threadsafe", side_effect=RuntimeError("closed")):
            screen._load_servers_bg(refresh=True)
            await asyncio.sleep(0.1)
        self.assertEqual(screen.servers, [{"name": "a", "command": "x"}])

    async def test_render_status_exception(self):
        screen = MCPScreen.__new__(MCPScreen)
        mgr = MagicMock()
        mgr.get_server_status.side_effect = Exception("boom")
        screen.mm = mgr
        screen.servers = [{"name": "a", "command": "x", "scope": "global"}]
        screen.search_query = ""
        opt_list = MagicMock()
        opt_list.highlighted = None
        screen.query_one = MagicMock(return_value=opt_list)
        screen._render_from_cache()
        self.assertTrue(screen.filtered_servers)

    async def test_add_server_row_status_exception(self):
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = MagicMock()
        screen.mm.get_server_status.side_effect = Exception("boom")
        opt_list = MagicMock()
        screen._add_server_row(opt_list, {"name": "s", "command": "c"}, {})

    async def test_add_server_row_plain_error(self):
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = MagicMock()
        screen.mm.get_server_status.return_value = {"error": "boom boom"}
        opt_list = MagicMock()
        screen._add_server_row(opt_list, {"name": "s", "command": "c"}, {})

    async def test_do_toggle_enabled_warms_server(self):
        # Enabling must run the targeted per-server warm (not the coalesced
        # global warmup, which can skip inside its freshness window).
        mgr = MagicMock()
        mgr.toggle_server = lambda name: True
        mgr.warm_server_async = AsyncMock()
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen._pending_toggles = set()
        screen._toggle_tasks = set()
        screen.refresh_list = MagicMock()
        screen._is_mounted = True
        host = _MCPToggleHost()
        async with host.run_test():
            await screen._do_toggle("s")
        mgr.warm_server_async.assert_awaited_once_with("s")
        self.assertGreater(host.footer_calls, 0)

    async def test_do_toggle_failure_notify(self):
        mgr = MagicMock()
        mgr.toggle_server = MagicMock(side_effect=Exception("bad"))
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen._pending_toggles = set()
        screen._toggle_tasks = set()
        screen.notify = MagicMock()
        screen.refresh_list = MagicMock()
        screen._is_mounted = True
        host = _MCPToggleHost()
        async with host.run_test():
            await screen._do_toggle("s")
        screen.notify.assert_called_once()

    async def test_do_toggle_cancelled_reraises(self):
        mgr = MagicMock()
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen._pending_toggles = set()
        screen._toggle_tasks = set()
        screen.notify = MagicMock()
        screen.refresh_list = MagicMock()
        screen._is_mounted = True
        host = _MCPToggleHost()
        async with host.run_test():
            with patch("widgets.presentation.screens.mcp.asyncio.to_thread", side_effect=asyncio.CancelledError()):
                with self.assertRaises(asyncio.CancelledError):
                    await screen._do_toggle("s")
        self.assertNotIn("s", screen._pending_toggles)

    async def test_on_input_submitted_target_none(self):
        screen = MCPScreen.__new__(MCPScreen)
        screen.filtered_servers = [None]
        opt_list = MagicMock()
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)
        event = MagicMock()
        event.input.id = "modal-search-input"
        screen.on_input_submitted(event)  # header row -> return

    async def test_on_option_selected_target_none(self):
        screen = MCPScreen.__new__(MCPScreen)
        screen.filtered_servers = [None]
        event = MagicMock()
        event.option_index = 0
        screen.on_option_list_option_selected(event)  # header row -> return

    def test_space_toggle_is_a_declared_binding(self):
        """`space: toggle` is advertised in the hint, so it must exist as a
        binding (P2-11) rather than only as a branch inside _on_key."""
        screen = MCPScreen.__new__(MCPScreen)
        screen._toggle_highlighted = MagicMock()
        self.assertIn("space", {binding[0] for binding in MCPScreen.BINDINGS})
        self.assertIn("toggle_highlighted", MCPScreen.space_actions)
        screen.action_toggle_highlighted()
        screen._toggle_highlighted.assert_called_once()

    def test_on_key_space_query_one_does_not_crash(self):
        screen = MCPScreen.__new__(MCPScreen)
        screen._toggle_highlighted = MagicMock()
        screen.query_one = MagicMock(side_effect=Exception("no match"))
        screen.action_toggle_search = MagicMock()
        screen.action_select_cursor = MagicMock()

        event = MagicMock()
        event.key = "space"
        screen._on_key(event)
        # Space no longer toggles from _on_key: it is a binding now.
        screen._toggle_highlighted.assert_not_called()


if __name__ == "__main__":
    unittest.main()
