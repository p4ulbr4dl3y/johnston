import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from textual.app import App

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

                # Details
                await pilot.press("x")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()

    async def test_linters_screen_bindings_include_keys(self):
        screen = LintersScreen()
        keys = [b[0] for b in screen.BINDINGS]
        self.assertIn("x", keys)
        self.assertIn("escape", keys)
        self.assertNotIn("i", keys)
        self.assertNotIn("u", keys)
