import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from textual.app import App
from textual.widgets import OptionList

from widgets.screens.help import HelpScreen
from widgets.screens.mcp import MCPScreen
from widgets.screens.model import ModelScreen
from widgets.screens.providers import ApiKeyInputScreen, ProvidersScreen
from widgets.screens.subagents import SubagentsScreen
from widgets.screens.tasks import TasksListScreen


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

    async def test_mcp_screen_pilot(self):
        with patch("widgets.screens.mcp.get_mcp_manager") as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.load_servers.return_value = [
                {"name": "srv1", "command": "python", "disabled": False, "mode": "eager", "scope": "global"}
            ]
            mock_mgr.toggle_server.return_value = False
            mock_mgr.toggle_mode.return_value = "lazy"
            mock_get_mgr.return_value = mock_mgr

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
        from core.subagent_tracker import SubagentTracker
        tracker = SubagentTracker.get_instance()
        tracker.storage_dir = self.test_dir
        tracker.sessions.clear()
        tracker.create_session("sub-p1", "Pilot subagent", "do work", "general", False)

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

            # Step 1: Toggle "Red" with Space, then press Enter
            await pilot.press("space")
            await pilot.pause()
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

    async def test_ask_user_wizard_deselect_preserves_highlight_index(self):
        from widgets.screens.ask_user import AskUserWizardScreen

        questions = [
            {"question_text": "Pick item", "options": ["Item 0", "Item 1", "Item 2"]}
        ]
        screen = AskUserWizardScreen(questions)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            opt_list = screen.query_one("#options-list", OptionList)

            # Move down to "Item 1" (index 1)
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(opt_list.highlighted, 1)

            # Select Item 1 with Space
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(screen.answers.get(0, {}).get("answer"), "Item 1")
            self.assertEqual(opt_list.highlighted, 1)

            # Deselect Item 1 with Space
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(screen.answers.get(0, {}).get("answer"), "")
            self.assertEqual(opt_list.highlighted, 1)

    async def test_write_in_input_down_key_does_not_advance_page(self):
        from textual.widgets import Input

        from widgets.screens.ask_user import AskUserWizardScreen

        questions = [
            {"question_text": "Enter custom text", "options": []},
            {"question_text": "Question 2", "options": []}
        ]
        screen = AskUserWizardScreen(questions)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            input_field = screen.query_one("#write-in-input", Input)

            self.assertEqual(screen.q_idx, 0)
            await pilot.press("a", "b", "c")
            await pilot.pause()

            # Press down arrow inside input
            await pilot.press("down")
            await pilot.pause()

            # Verify q_idx is still 0 (did NOT jump to next page)
            self.assertEqual(screen.q_idx, 0)
            self.assertEqual(input_field.value, "abc")


if __name__ == "__main__":
    unittest.main()



