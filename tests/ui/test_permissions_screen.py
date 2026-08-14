import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App
from textual.events import Key

from widgets.commands import COMMAND_REGISTRY
from widgets.screens.permissions import PermissionsScreen


class DummyHostApp(App[None]):
    def __init__(self, screen_to_test):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.project_dir = os.getcwd()

    def on_mount(self) -> None:
        self.push_screen(self.screen_to_test)

    def refresh_status_footer(self):
        pass


def _make_mcp_mock(active=None, cached=None):
    """Returns an MCP manager mock with async tool discovery APIs."""
    mgr = MagicMock()
    mgr.get_cached_tools.return_value = cached if cached is not None else []
    mgr.ensure_tools_ready_async = AsyncMock(return_value=None)
    mgr.get_active_tools_async = AsyncMock(return_value=active if active is not None else [])
    return mgr


def _mcp_tool(exposed_name, server, raw_name=None, description=""):
    return {
        "type": "function",
        "function": {"name": exposed_name, "description": description},
        "_mcp_server": server,
        "_mcp_tool_name": raw_name or exposed_name,
    }


class TestPermissionsScreenPilot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.config_patcher = patch("core.permission_manager.CONFIG_FILE", os.path.join(self.test_dir, "config.json"))
        self.config_patcher.start()
        self.mcp_patcher = patch("core.infrastructure.mcp.get_mcp_manager", return_value=_make_mcp_mock())
        self.mcp_patcher.start()

    def tearDown(self):
        self.mcp_patcher.stop()
        self.config_patcher.stop()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_permissions_command_registered(self):
        self.assertIn("/permissions", COMMAND_REGISTRY)
        self.assertIn("/perms", COMMAND_REGISTRY)

    async def test_permissions_screen_pilot(self):
        screen = PermissionsScreen()
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()

            # Filter items by 'shell': finds the shell tool
            await pilot.press("s", "h", "e", "l", "l")
            await pilot.pause()
            self.assertTrue(any(it["name"] == "shell" for it in screen.filtered_items))

            # Cycle action for highlighted item (enter key)
            await pilot.press("enter")
            await pilot.pause()

            # Close screen
            await pilot.press("escape")
            await pilot.pause()

    async def test_action_quit_app(self):
        screen = PermissionsScreen()
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(screen.app, "exit") as mock_exit:
                screen.action_quit_app()
                mock_exit.assert_called_once()

    async def test_on_mount_focus_exception(self):
        screen = PermissionsScreen()
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            real_qo = screen.query_one

            def raising_qo(selector, *args, **kwargs):
                if "modal-search-input" in str(selector):
                    raise Exception("boom")
                return real_qo(selector, *args, **kwargs)

            screen.query_one = raising_qo
            screen.on_mount()  # must not raise

    def test_cycle_action_all_states(self):
        screen = PermissionsScreen()
        self.assertEqual(screen._cycle_action("ALLOW"), "ask")
        self.assertEqual(screen._cycle_action("ask"), "deny")
        self.assertEqual(screen._cycle_action("deny"), "allow")

    async def test_on_option_list_option_selected(self):
        screen = PermissionsScreen()
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            screen.refresh_list()
            sel_idx = next(i for i, it in enumerate(screen.filtered_items) if it["type"] == "tool")
            event = MagicMock()
            event.option_index = sel_idx
            before = screen.filtered_items[sel_idx]["action"]
            screen.on_option_list_option_selected(event)
            self.assertNotEqual(screen.filtered_items[sel_idx]["action"], before)

    async def test_refresh_list_renders_all_statuses(self):
        screen = PermissionsScreen()
        async with DummyHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.pm = MagicMock()
            screen.pm.get_effective_permissions.return_value = {
                "default": "ask",
                "tools": {"read": "deny", "create": "allow", "web_fetch": "ask"},
            }
            opt_list = MagicMock()
            opt_list.highlighted = None
            screen.query_one = MagicMock(return_value=opt_list)
            screen.refresh_list()
            joined = "\n".join(str(c.args[0]) for c in opt_list.add_option.call_args_list)
            self.assertIn("[DENY] read", joined)
            self.assertIn("[ALLOW] create", joined)
            self.assertIn("[ASK] web_fetch", joined)
            self.assertIn("Builtin", joined)

    def _setup_key_harness(self, screen, highlighted=None, filtered=None, focus=True):
        if filtered is not None:
            screen.filtered_items = filtered
        opt_list = MagicMock()
        opt_list.highlighted = highlighted
        search_input = MagicMock()
        search_input.has_focus = focus

        def fake_qo(selector, *args, **kwargs):
            if "modal-search-input" in str(selector):
                return search_input
            return opt_list

        screen.query_one = MagicMock(side_effect=fake_qo)
        return opt_list, search_input

    async def test_on_key_down_up_when_search_focused(self):
        screen = PermissionsScreen()
        async with DummyHostApp(screen).run_test() as pilot:
            await pilot.pause()
            filtered = [{"type": "tool", "name": "read", "label": "read", "desc": "", "action": "ask"}]

            # No highlight -> highlight first item
            opt_list, _ = self._setup_key_harness(screen, highlighted=None, filtered=filtered)
            event = Key(key="down", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            self.assertEqual(opt_list.highlighted, 0)
            event.prevent_default.assert_called()
            event.stop.assert_called()

            # Highlighted -> move cursor down
            opt_list, _ = self._setup_key_harness(screen, highlighted=1, filtered=filtered)
            event = Key(key="down", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            opt_list.action_cursor_down.assert_called_once()

            # Highlighted -> move cursor up
            opt_list, _ = self._setup_key_harness(screen, highlighted=1, filtered=filtered)
            event = Key(key="up", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            opt_list.action_cursor_up.assert_called_once()

    async def test_on_key_down_search_not_focused(self):
        screen = PermissionsScreen()
        async with DummyHostApp(screen).run_test() as pilot:
            await pilot.pause()
            self._setup_key_harness(screen, highlighted=0, filtered=[], focus=False)
            event = Key(key="up", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)
            event.prevent_default.assert_not_called()

    async def test_on_key_down_exception(self):
        screen = PermissionsScreen()
        async with DummyHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.query_one = MagicMock(side_effect=Exception("boom"))
            event = Key(key="down", character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            screen._on_key(event)  # must not raise

    # --- New grouped-layout / MCP tests ---

    async def test_sections_builtin_and_mcp(self):
        mgr = _make_mcp_mock(
            cached=[
                _mcp_tool("alpha_tool", "alpha", description="alpha desc"),
                _mcp_tool("beta_tool", "beta", description="beta desc"),
            ]
        )
        with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mgr):
            screen = PermissionsScreen()
            items = screen._get_items()

        headers = [it for it in items if it["type"] == "group_header"]
        self.assertEqual([h["label"] for h in headers], ["Builtin", "alpha", "beta"])

        tool_names = [it["name"] for it in items if it["type"] == "tool"]
        # Builtin tools use raw registry names (no TOOL_LABELS mapping)
        self.assertIn("read", tool_names)
        self.assertIn("create", tool_names)
        # MCP tools appear under their exposed names
        self.assertIn("alpha_tool", tool_names)
        self.assertIn("beta_tool", tool_names)

    async def test_search_hides_group_headers(self):
        mgr = _make_mcp_mock(cached=[_mcp_tool("alpha_tool", "alpha", description="alpha desc")])
        with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mgr):
            screen = PermissionsScreen()
            async with DummyHostApp(screen).run_test() as pilot:
                await pilot.pause()
                screen.search_query = "alpha"
                screen.refresh_list()

        self.assertTrue(screen.filtered_items)
        self.assertTrue(all(it["type"] == "tool" for it in screen.filtered_items))
        self.assertIn("alpha_tool", [it["name"] for it in screen.filtered_items])

    async def test_toggle_mcp_tool_uses_exposed_name(self):
        mgr = _make_mcp_mock(
            cached=[_mcp_tool("srv__search", "srv", raw_name="search", description="search on srv")]
        )
        with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mgr):
            screen = PermissionsScreen()
            async with DummyHostApp(screen).run_test() as pilot:
                await pilot.pause()
                screen.refresh_list()
                idx = next(i for i, it in enumerate(screen.filtered_items) if it["name"] == "srv__search")
                with patch.object(screen.pm, "update_permission", wraps=screen.pm.update_permission) as mock_upd:
                    # Default for MCP tools is 'allow', so cycle: allow -> ask -> deny.
                    screen.toggle_selected_permission(idx)
                    screen.toggle_selected_permission(idx)
                mock_upd.assert_called_with("tool", "srv__search", "deny")

    async def test_toggle_group_header_noop(self):
        screen = PermissionsScreen()
        async with DummyHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.refresh_list()
            hdr_idx = next(i for i, it in enumerate(screen.filtered_items) if it["type"] == "group_header")
            with patch.object(screen.pm, "update_permission") as mock_upd:
                screen.toggle_selected_permission(hdr_idx)
            mock_upd.assert_not_called()

    async def test_mcp_tools_load_in_background(self):
        mgr = _make_mcp_mock(active=[_mcp_tool("bg_tool", "bg", description="bg desc")])
        with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mgr):
            screen = PermissionsScreen()
            async with DummyHostApp(screen).run_test() as pilot:
                await pilot.pause()
                await pilot.pause(0.05)

        tool_names = [it["name"] for it in screen._get_items() if it["type"] == "tool"]
        self.assertIn("bg_tool", tool_names)
        # The background fetch also refreshed the rendered list
        self.assertTrue(any(it["name"] == "bg_tool" for it in screen.filtered_items))

    async def test_mcp_background_load_exception_safe(self):
        mgr = _make_mcp_mock()
        mgr.get_active_tools_async = AsyncMock(side_effect=RuntimeError("server down"))
        with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mgr):
            screen = PermissionsScreen()
            async with DummyHostApp(screen).run_test() as pilot:
                await pilot.pause()
                await pilot.pause(0.05)
        # UI must not crash; cached items still renderable
        tool_names = [it["name"] for it in screen._get_items() if it["type"] == "tool"]
        self.assertIn("read", tool_names)


if __name__ == "__main__":
    unittest.main()
