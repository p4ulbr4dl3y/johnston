import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from widgets.screens.help import HelpScreen
from widgets.screens.mcp import MCPScreen
from widgets.screens.model import ModelScreen, VisionWarningScreen
from widgets.screens.policy import PolicyScreen
from widgets.screens.providers import ApiKeyInputScreen, ProvidersScreen
from widgets.screens.subagent_screen import SubagentViewScreen

from widgets.screens.subagents import SubagentsScreen
from widgets.screens.tasks import TaskConsoleScreen, TasksListScreen


class DummyHostApp(App[None]):
    """Host app for testing Textual modal screens with pilot."""

    def __init__(self, screen_to_test):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.dismiss_result = None
        self.background_tasks = []

    def on_mount(self) -> None:
        def callback(res=None):
            self.dismiss_result = res
        self.push_screen(self.screen_to_test, callback=callback)

    def refresh_status_footer(self):
        pass


class TestScreensPilot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    async def test_policy_screen_pilot_toggle_and_tabs(self):
        with patch("core.policy_config.POLICY_CONFIG_PATH", os.path.join(self.test_dir, "policy.json")):
            screen = PolicyScreen(initial_tab="rules")
            app = DummyHostApp(screen)


            async with app.run_test() as pilot:
                await pilot.pause()
                # Test pressing 'a' (allow), 's' (ask), 'b' (block)
                await pilot.press("a")
                await pilot.press("s")
                await pilot.press("b")
                await pilot.pause()

                # Switch tab to budgets
                await pilot.press("tab")
                await pilot.pause()
                self.assertEqual(screen.active_tab, "budgets")

                # Cycle budget limit
                await pilot.press("enter")
                await pilot.pause()

                # Close screen
                await pilot.press("escape")
                await pilot.pause()

    async def test_mcp_screen_pilot(self):
        with patch("widgets.screens.mcp.MCPManager") as mock_mgr_cls:
            mock_mgr = MagicMock()
            mock_mgr.load_servers.return_value = [
                {"name": "srv1", "command": "python", "disabled": False, "mode": "eager", "scope": "global"}
            ]
            mock_mgr.toggle_server.return_value = False
            mock_mgr.toggle_mode.return_value = "lazy"
            mock_mgr_cls.return_value = mock_mgr

            screen = MCPScreen()
            app = DummyHostApp(screen)

            async with app.run_test() as pilot:
                await pilot.pause()
                # Toggle disabled state
                await pilot.press("enter")
                await pilot.pause()

                # Toggle eager/lazy mode
                await pilot.press("m")
                await pilot.pause()

                # Close
                await pilot.press("escape")
                await pilot.pause()

    async def test_model_screen_pilot_tab_switching(self):
        models_data = {"prov1": {"name": "Provider 1", "models": ["model-a", "model-b"]}}
        screen = ModelScreen(models_data=models_data, current_model="model-a", current_provider="prov1")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Switch to vision tab
            await pilot.press("tab")
            await pilot.pause()

            # Close
            await pilot.press("escape")
            await pilot.pause()

    async def test_providers_screen_pilot(self):
        providers = {
            "opencode": {"key": "opencode", "name": "OpenCode"},
            "openai": {"key": "openai", "name": "OpenAI"}
        }
        screen = ProvidersScreen(providers=providers, active_key="opencode", configured_keys={})
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_api_key_input_screen_pilot(self):
        screen = ApiKeyInputScreen("OpenAI", "openai", "sk-12345")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_tasks_list_screen_pilot(self):
        mock_task = MagicMock()
        mock_task.task_id = "task-1"
        mock_task.command = "npm run test"
        mock_task.is_running = True

        screen = TasksListScreen()
        app = DummyHostApp(screen)
        app.background_tasks = [mock_task]

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("k")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_subagents_screen_pilot(self):
        from core.subagent_tracker import SUBAGENTS_DIR, SubagentTracker
        tracker = SubagentTracker.get_instance()
        tracker.storage_dir = self.test_dir
        tracker.sessions.clear()
        sess = tracker.create_session("sub-p1", "Pilot subagent", "do work", "general", False)

        try:
            screen = SubagentsScreen()
            app = DummyHostApp(screen)

            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
        finally:
            tracker.sessions.clear()


    async def test_help_screen_pilot(self):
        screen = HelpScreen()
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    async def test_ask_user_wizard_screen_pilot(self):
        from widgets.screens.ask_user import AskUserWizardScreen
        questions = [
            {"question_text": "Pick color", "options": ["Red", "Blue"]},
            {"question_text": "Enter name", "options": []}
        ]
        screen = AskUserWizardScreen(questions)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0

            # Step 1: Select "Red" and press enter
            await pilot.press("enter")
            await pilot.pause()

            screen._mount_time = 0
            # Step 2: Type custom input and press enter
            await pilot.press("j", "o", "h", "n")
            await pilot.press("enter")
            await pilot.pause()

            screen._mount_time = 0
            # Step 3: Confirm summary step
            await pilot.press("enter")
            await pilot.pause()

            self.assertIn("Question: Pick color", str(app.dismiss_result))
            self.assertIn("Answer: Red", str(app.dismiss_result))



if __name__ == "__main__":
    unittest.main()


