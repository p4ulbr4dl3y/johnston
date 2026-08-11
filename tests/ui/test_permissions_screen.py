import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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


class TestPermissionsScreenPilot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.config_patcher = patch("core.permission_manager.CONFIG_FILE", os.path.join(self.test_dir, "config.json"))
        self.config_patcher.start()

    def tearDown(self):
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

            # Filter items by 'shell': finds the shell tool and ShellGuard
            await pilot.press("s", "h", "e", "l", "l")
            await pilot.pause()
            self.assertTrue(any(it["name"] == "shell" for it in screen.filtered_items))
            self.assertTrue(any(it["name"] == "shell_guard" for it in screen.filtered_items))

            # Cycle action for highlighted item (enter key)
            await pilot.press("enter")
            await pilot.pause()

            # Close screen
            await pilot.press("escape")
            await pilot.pause()

    async def test_shell_guard_toggle(self):
        screen = PermissionsScreen()
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()

            items = screen._get_items()
            sg_item = next((it for it in items if it["name"] == "shell_guard"), None)
            self.assertIsNotNone(sg_item)
            self.assertEqual(sg_item["label"], "ShellGuard")

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

    async def test_shell_guard_toggle_off(self):
        screen = PermissionsScreen()
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            screen.refresh_list()
            sg_idx = next(i for i, it in enumerate(screen.filtered_items) if it["type"] == "shell_guard")
            before = screen.filtered_items[sg_idx]["action"]
            screen.toggle_selected_permission(sg_idx)
            self.assertNotEqual(screen.filtered_items[sg_idx]["action"], before)

    async def test_on_option_list_option_selected(self):
        screen = PermissionsScreen()
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            screen.refresh_list()
            event = MagicMock()
            event.option_index = 0
            before = screen.filtered_items[0]["action"]
            screen.on_option_list_option_selected(event)
            self.assertNotEqual(screen.filtered_items[0]["action"], before)

    async def test_refresh_list_renders_all_statuses(self):
        screen = PermissionsScreen()
        async with DummyHostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.pm = MagicMock()
            screen.pm.get_effective_permissions.return_value = {
                "default": "ask",
                "tools": {"read": "deny", "create": "allow", "web_fetch": "ask"},
                "shell_guard": {"enabled": True},
            }
            opt_list = MagicMock()
            opt_list.highlighted = None
            screen.query_one = MagicMock(return_value=opt_list)
            screen.refresh_list()
            joined = "\n".join(str(c.args[0]) for c in opt_list.add_option.call_args_list)
            self.assertIn("[DENY] Read", joined)
            self.assertIn("[ALLOW] Create", joined)
            self.assertIn("[ASK] WebFetch", joined)
            self.assertIn("[ON] ShellGuard", joined)

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
            filtered = [{"type": "tool", "name": "read", "label": "Read", "desc": "", "action": "ask"}]

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


if __name__ == "__main__":
    unittest.main()
