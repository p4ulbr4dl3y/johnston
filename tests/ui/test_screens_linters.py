import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from textual.app import App
from textual.widgets import OptionList

from widgets.screens.linters import LintersScreen


class DummyHostApp(App[None]):
    def __init__(self, screen_to_test):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.dismiss_result = None
        self.background_tasks = []

    def on_mount(self) -> None:
        self.push_screen(self.screen_to_test)

    def refresh_status_footer(self):
        pass


class TestLintersScreenPilot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def _mock_mgr(self):
        mgr = MagicMock()
        mgr.load_linters.return_value = [
            {
                "name": "python",
                "label": "Python",
                "enabled": True,
                "install": "uvx",
                "extensions": [".py"],
                "cmd": ["uvx", "ruff", "check", "{file}"],
            },
            {
                "name": "php",
                "label": "PHP",
                "enabled": False,
                "install": "brew",
                "extensions": [".php"],
                "cmd": ["php", "-l", "{file}"],
            },
        ]
        mgr.scan_available.return_value = {"python": True, "php": False}
        return mgr

    async def test_linters_screen_pilot(self):
        with patch("widgets.screens.linters.get_linters_manager") as mock_get:
            mock_mgr = self._mock_mgr()
            mock_get.return_value = mock_mgr
            screen = LintersScreen()
            app = DummyHostApp(screen)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Toggle python (enabled -> disabled)
                await pilot.press("enter")
                await pilot.pause()
                mock_mgr.set_enabled.assert_called_with("python", False)

                # Move to php (index 1)
                await pilot.press("down")
                await pilot.pause()

                # Toggle php (disabled -> enabled)
                await pilot.press("enter")
                await pilot.pause()
                mock_mgr.set_enabled.assert_called_with("php", True)

                # Close screen
                await pilot.press("escape")
                await pilot.pause()

    async def test_linters_search_filter_and_no_match(self):
        with patch("widgets.screens.linters.get_linters_manager") as mock_get:
            mock_mgr = self._mock_mgr()
            mock_get.return_value = mock_mgr
            screen = LintersScreen()
            app = DummyHostApp(screen)

            async with app.run_test() as pilot:
                await pilot.pause()

                # Typing filters the list
                await pilot.press("p", "y")
                await pilot.pause()
                self.assertEqual([lint["name"] for lint in screen.filtered_linters], ["python"])

                # No matches -> placeholder option
                await pilot.press("z", "z")
                await pilot.pause()
                self.assertEqual(screen.filtered_linters, [])
                opt_list = screen.query_one("#linters-option-list", OptionList)
                self.assertIn("*No matching linters found*", opt_list.get_option_at_index(0).prompt)

    async def test_linters_screen_no_linters_configured(self):
        with patch("widgets.screens.linters.get_linters_manager") as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.load_linters.return_value = []
            mock_mgr.scan_available.return_value = {}
            mock_get.return_value = mock_mgr
            screen = LintersScreen()
            app = DummyHostApp(screen)

            async with app.run_test() as pilot:
                await pilot.pause()
                self.assertEqual(screen.filtered_linters, [])
                opt_list = screen.query_one("#linters-option-list", OptionList)
                self.assertIn("*No linters configured*", opt_list.get_option_at_index(0).prompt)

    async def test_linters_quit_app_and_mount_focus_exception(self):
        with patch("widgets.screens.linters.get_linters_manager") as mock_get:
            mock_mgr = self._mock_mgr()
            mock_get.return_value = mock_mgr
            screen = LintersScreen()
            app = DummyHostApp(screen)

            async with app.run_test() as pilot:
                await pilot.pause()

                with patch.object(screen.app, "exit") as mock_exit:
                    screen.action_quit_app()
                    mock_exit.assert_called_once()

                # on_mount swallows focus errors
                real_q = screen.query_one

                def fake_q(selector, *args, **kwargs):
                    if selector == "#modal-search-input":
                        raise Exception("focus boom")
                    return real_q(selector, *args, **kwargs)

                with patch.object(screen, "query_one", side_effect=fake_q):
                    screen.on_mount()

    def test_on_key_down_sets_highlight_when_none(self):
        with patch("widgets.screens.linters.get_linters_manager") as mock_get:
            mock_mgr = self._mock_mgr()
            mock_get.return_value = mock_mgr
            screen = LintersScreen()
            screen.filtered_linters = [{"name": "python"}, {"name": "php"}]
            opt_list = MagicMock()
            opt_list.highlighted = None
            search_input = MagicMock()
            search_input.has_focus = True
            screen.query_one = MagicMock(
                side_effect=lambda selector, *a: opt_list if "option-list" in selector else search_input
            )

            event = MagicMock(key="down")
            screen._on_key(event)
            self.assertEqual(opt_list.highlighted, 0)
            event.prevent_default.assert_called_once()
            event.stop.assert_called_once()

    def test_on_key_up_calls_cursor_up(self):
        with patch("widgets.screens.linters.get_linters_manager") as mock_get:
            mock_mgr = self._mock_mgr()
            mock_get.return_value = mock_mgr
            screen = LintersScreen()
            screen.filtered_linters = [{"name": "python"}]
            opt_list = MagicMock()
            opt_list.highlighted = 0
            search_input = MagicMock()
            search_input.has_focus = True
            screen.query_one = MagicMock(
                side_effect=lambda selector, *a: opt_list if "option-list" in selector else search_input
            )

            screen._on_key(MagicMock(key="up"))
            opt_list.action_cursor_up.assert_called_once()

    def test_on_key_query_one_exception_swallowed(self):
        with patch("widgets.screens.linters.get_linters_manager") as mock_get:
            mock_mgr = self._mock_mgr()
            mock_get.return_value = mock_mgr
            screen = LintersScreen()
            screen.query_one = MagicMock(side_effect=Exception("boom"))
            screen._on_key(MagicMock(key="down"))  # must not raise

    def test_input_submitted_no_name_returns(self):
        with patch("widgets.screens.linters.get_linters_manager") as mock_get:
            mock_mgr = self._mock_mgr()
            mock_get.return_value = mock_mgr
            screen = LintersScreen()
            screen.filtered_linters = [{"label": "NoName"}]
            opt_list = MagicMock()
            opt_list.highlighted = 0
            screen.query_one = MagicMock(return_value=opt_list)
            event = MagicMock(input=MagicMock(id="modal-search-input"))

            screen.on_input_submitted(event)
            mock_mgr.set_enabled.assert_not_called()

    def test_option_selected_toggles_linter(self):
        with patch("widgets.screens.linters.get_linters_manager") as mock_get:
            mock_mgr = self._mock_mgr()
            mock_get.return_value = mock_mgr
            screen = LintersScreen()
            screen.filtered_linters = [
                {"name": "python", "enabled": True},
                {"name": "php", "enabled": False},
            ]
            opt_list = MagicMock()
            opt_list.highlighted = 1
            screen.query_one = MagicMock(return_value=opt_list)

            screen.on_option_list_option_selected(MagicMock(option_index=1))
            mock_mgr.set_enabled.assert_called_with("php", True)
            self.assertEqual(opt_list.highlighted, 1)

    def test_option_selected_no_name_returns(self):
        with patch("widgets.screens.linters.get_linters_manager") as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.load_linters.return_value = [{"label": "Ghost"}]
            mock_mgr.scan_available.return_value = {}
            mock_get.return_value = mock_mgr
            screen = LintersScreen()
            screen.filtered_linters = [{"label": "Ghost"}]
            screen.query_one = MagicMock(return_value=MagicMock())

            screen.on_option_list_option_selected(MagicMock(option_index=0))
            mock_mgr.set_enabled.assert_not_called()

    async def test_linters_screen_bindings_include_keys(self):
        screen = LintersScreen()
        keys = [b[0] for b in screen.BINDINGS]
        self.assertNotIn("x", keys)
        self.assertIn("escape", keys)
        self.assertNotIn("i", keys)
        self.assertNotIn("u", keys)
