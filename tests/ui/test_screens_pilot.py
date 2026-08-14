import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from textual.app import App
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from core.infrastructure.tasks.manager import TaskManager
from widgets.screens.help import HelpScreen
from widgets.screens.mcp import MCPScreen
from widgets.screens.model import ModelScreen
from widgets.screens.providers import ApiKeyInputScreen, ProvidersScreen
from widgets.screens.subagent_screen import SubagentViewScreen
from widgets.screens.tasks import ShellTasksScreen, SubagentsScreen, TaskConsoleScreen


class DummyHostApp(App[None]):
    """Host app for testing Textual modal screens with pilot."""

    def __init__(self, screen_to_test):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.dismiss_result = None
        self.task_manager = TaskManager()

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
                {"name": "srv1", "command": "python", "disabled": False, "scope": "global"}
            ]
            mock_mgr.toggle_server.return_value = False
            mock_get_mgr.return_value = mock_mgr

            screen = MCPScreen()
            app = DummyHostApp(screen)

            async with app.run_test() as pilot:
                await pilot.pause()
                # Toggle disabled state
                await pilot.press("enter")
                await pilot.pause()

                # Close
                await pilot.press("escape")
                await pilot.pause()

    async def test_model_screen_pilot(self):
        models_data = {"prov1": {"name": "Provider 1", "models": ["model-a", "model-b"]}}
        screen = ModelScreen(models_data=models_data, current_model="model-a", current_provider="prov1")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Close
            await pilot.press("escape")
            await pilot.pause()

    async def test_providers_screen_pilot(self):
        providers = {"opencode": {"key": "opencode", "name": "OpenCode"}, "openai": {"key": "openai", "name": "OpenAI"}}
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

    async def test_subagents_screen_empty_pilot(self):
        screen = SubagentsScreen()
        app = DummyHostApp(screen)
        app.sm = MagicMock()
        app.sm.get_subagents_for_parent.return_value = []

        async with app.run_test() as pilot:
            await pilot.pause()
            # Calling update_tasks_list again when signatures are unchanged
            screen.update_tasks_list()
            await pilot.press("escape")
            await pilot.pause()

    async def test_subagents_screen_option_selected_pilot(self):
        from textual.widgets.option_list import Option

        sub_session = MagicMock()
        sub_session.id = "sub-1"
        sub_session.status = "running"
        sub_session.description = "sub task"

        screen = SubagentsScreen()
        app = DummyHostApp(screen)
        app.current_session_id = "main-1"
        app.sm = MagicMock()
        app.sm.get_subagents_for_parent.return_value = [sub_session]

        async with app.run_test() as pilot:
            await pilot.pause()

            opt_list = screen.query_one("#subagents-option-list", OptionList)
            screen.update_tasks_list()
            with patch.object(app, "push_screen") as mock_push:
                # index 1 = sub task (running, first selectable after Running header)
                screen.on_option_list_option_selected(OptionList.OptionSelected(opt_list, Option("sub task"), 1))
                mock_push.assert_called_once()
                self.assertIsInstance(mock_push.call_args[0][0], SubagentViewScreen)

    async def test_subagents_screen_kill_task_pilot(self):

        sub_session = MagicMock()
        sub_session.id = "sub-1"
        sub_session.status = "running"
        sub_session.description = "long " + "a" * 40
        sub_session.async_task = MagicMock()
        sub_session.async_task.done.return_value = False
        sub_session.finish = MagicMock()

        screen = SubagentsScreen()
        app = DummyHostApp(screen)
        app.current_session_id = "main-1"
        app.sm = MagicMock()
        app.sm.get_subagents_for_parent.return_value = [sub_session]

        async with app.run_test() as pilot:
            await pilot.pause()
            screen.update_tasks_list()

            # One running subagent -> one Running group: [None, sub_session]
            # Kill first subagent
            mock_opt_list = MagicMock()
            mock_opt_list.highlighted = 1
            with patch.object(screen, "query_one", return_value=mock_opt_list):
                await screen.action_kill_task()
            sub_session.async_task.cancel.assert_called_once()
            sub_session.finish.assert_called_once_with("cancelled", "Terminated from subagents menu")

            # Kill header row -> noop
            mock_opt_list.highlighted = 0
            with patch.object(screen, "query_one", return_value=mock_opt_list):
                await screen.action_kill_task()

            # Test update_tasks_list when current_highlighted >= len(tasks)
            mock_opt_list.highlighted = 99
            screen._last_signatures = None
            with patch.object(screen, "query_one", return_value=mock_opt_list):
                screen.update_tasks_list()

            with patch.object(screen.app, "exit") as mock_exit:
                screen.action_quit_app()
                mock_exit.assert_called_once()

                await pilot.press("escape")
                await pilot.pause()

        # Calling update when not mounted
        screen._is_mounted = False
        screen.update_tasks_list()

    async def test_task_console_screen_pilot(self):
        from core.infrastructure.tasks.output import OutputBuffer

        mock_task = MagicMock()
        mock_task.command = "python long_running_script.py"
        mock_task.output = OutputBuffer()
        mock_task.output.append("Line 1\r\n")
        mock_task.output.append("Line 2\n")

        screen = TaskConsoleScreen(mock_task)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(screen.printed_count, 2)

            # Test updating log with new lines
            mock_task.output.append("Line 3\n")
            screen.update_log()
            self.assertEqual(screen.printed_count, 3)

            await pilot.press("escape")
            await pilot.pause()

    async def test_shell_screen_pilot(self):
        task_normal = MagicMock()
        task_normal.id = "task-norm"
        task_normal.task_id = "task-norm"
        task_normal.kind = "shell"
        task_normal.command = "norm task"
        task_normal.is_background = True
        task_normal.is_running = False
        task_normal.session_id = "main-1"

        screen = ShellTasksScreen()
        app = DummyHostApp(screen)
        app.task_manager.register(task_normal)
        app.current_session_id = "main-1"

        async with app.run_test() as pilot:
            await pilot.pause()
            screen.update_tasks_list()

            opt_list = screen.query_one("#shell-option-list", OptionList)
            with patch.object(app, "push_screen") as mock_push:
                # index 1 = task (Completed header@0, task@1)
                screen.on_option_list_option_selected(OptionList.OptionSelected(opt_list, Option("norm task"), 1))
                mock_push.assert_called_once()
                self.assertIsInstance(mock_push.call_args[0][0], TaskConsoleScreen)

            await pilot.press("escape")
            await pilot.pause()

    async def test_shell_screen_kill_pilot(self):
        task_run = MagicMock()
        task_run.id = "task-run"
        task_run.task_id = "task-run"
        task_run.kind = "shell"
        task_run.command = "sleep 100"
        task_run.is_background = True
        task_run.is_running = True
        task_run.session_id = "main-1"

        async def mock_kill_async():
            task_run.is_running = False

        task_run.kill = MagicMock(side_effect=mock_kill_async)

        screen = ShellTasksScreen()
        app = DummyHostApp(screen)
        app.task_manager.register(task_run)
        app.current_session_id = "main-1"
        app.sm = MagicMock()

        async with app.run_test() as pilot:
            await pilot.pause()
            screen.update_tasks_list()

            mock_opt_list = MagicMock()
            mock_opt_list.highlighted = 1
            with patch.object(screen, "query_one", return_value=mock_opt_list):
                await screen.action_kill_task()
            task_run.kill.assert_called_once()
            self.assertFalse(task_run.is_running)

            # Kill header row -> noop
            mock_opt_list.highlighted = 0
            with patch.object(screen, "query_one", return_value=mock_opt_list):
                await screen.action_kill_task()

            await pilot.press("escape")
            await pilot.pause()

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
            {"question_text": "Enter name", "options": []},
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

        questions = [{"question_text": "Pick item", "options": ["Item 0", "Item 1", "Item 2"]}]
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
            {"question_text": "Question 2", "options": []},
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

    async def test_write_in_input_cleared_between_questions(self):
        from textual.widgets import Input

        from widgets.screens.ask_user import AskUserWizardScreen

        questions = [{"question_text": "Q1", "options": ["Opt1"]}, {"question_text": "Q2", "options": ["Opt2"]}]
        screen = AskUserWizardScreen(questions)
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            screen._mount_time = 0
            # Highlight Write-in on Q1 and type text
            await pilot.press("down")  # Write-in...
            await pilot.pause()
            screen.focus_write_in_input()
            await pilot.pause()
            await pilot.press("f", "o", "o")
            await pilot.pause()
            screen._mount_time = 0
            await pilot.press("enter")
            await pilot.pause()

            # Q2 now active
            self.assertEqual(screen.q_idx, 1)
            input_field = screen.query_one("#write-in-input", Input)
            self.assertEqual(input_field.value, "")


if __name__ == "__main__":
    unittest.main()
