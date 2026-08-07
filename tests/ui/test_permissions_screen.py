import os
import shutil
import tempfile
import unittest

from textual.app import App

from core.commands import COMMAND_REGISTRY
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

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_permissions_command_registered(self):
        self.assertIn("/permissions", COMMAND_REGISTRY)
        self.assertIn("/perms", COMMAND_REGISTRY)

    async def test_permissions_screen_pilot(self):
        screen = PermissionsScreen(project_dir=self.test_dir)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()

            # Filter items
            await pilot.press("e", "x", "e", "c")
            await pilot.pause()

            # Cycle action for highlighted item (enter key)
            await pilot.press("enter")
            await pilot.pause()

            # Toggle scope (tab key)
            await pilot.press("tab")
            await pilot.pause()

            # Close screen
            await pilot.press("escape")
            await pilot.pause()


if __name__ == "__main__":
    unittest.main()
