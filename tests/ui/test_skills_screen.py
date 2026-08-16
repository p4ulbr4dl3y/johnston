import unittest
from unittest.mock import patch

from textual.app import App
from textual.events import Key
from textual.widgets import Input, Markdown, OptionList
from textual.widgets.option_list import Option

from core.application.skills.manager import Skill, SkillManager, SkillScope
from widgets.presentation.screens.skills import SkillDetailScreen, SkillsScreen


class DummyHostApp(App[None]):
    """Host app for testing Textual modal screens with pilot."""

    def __init__(self, screen_to_test):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.dismiss_result = None

    def on_mount(self) -> None:
        def callback(res=None):
            self.dismiss_result = res

        self.push_screen(self.screen_to_test, callback=callback)


def sample_skills():
    return [
        Skill(
            name="reviewer",
            description="Review the codebase for issues",
            location="/skills/reviewer/SKILL.md",
            content="Review code",
            scope=SkillScope.GLOBAL,
            hidden=False,
        ),
        Skill(
            name="test-runner",
            description="Run the test suite",
            location="/skills/test-runner/SKILL.md",
            content="Run tests",
            scope=SkillScope.PROJECT,
            hidden=True,
        ),
    ]


class TestSkillDetailScreen(unittest.IsolatedAsyncioTestCase):
    async def test_compose_default_scope_and_no_description(self):
        screen = SkillDetailScreen({"name": "alpha", "description": "   "})
        app = DummyHostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            text = " ".join(str(m._markdown) for m in screen.query(Markdown))
            self.assertIn("[GLOBAL]", text)
            self.assertIn("alpha", text)
            self.assertIn("No description provided.", text)

    async def test_compose_project_scope_and_description(self):
        screen = SkillDetailScreen({"name": "alpha", "description": "A useful skill", "scope": "project"})
        app = DummyHostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            text = " ".join(str(m._markdown) for m in screen.query(Markdown))
            self.assertIn("[PROJECT]", text)
            self.assertIn("A useful skill", text)

    async def test_action_cancel_dismisses_false(self):
        screen = SkillDetailScreen({"name": "alpha"})
        app = DummyHostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertFalse(app.dismiss_result)

    async def test_action_activate_dismisses_true(self):
        screen = SkillDetailScreen({"name": "alpha"})
        app = DummyHostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(app.dismiss_result)

    async def test_action_quit_app(self):
        screen = SkillDetailScreen({"name": "alpha"})
        app = DummyHostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(screen.app, "exit") as mock_exit:
                screen.action_quit_app()
                mock_exit.assert_called_once()


class TestSkillsScreen(unittest.IsolatedAsyncioTestCase):
    async def _run(self, *keys):
        """Run the screen with sample skills, executing assertions inside the mounted app context."""
        with patch.object(SkillManager, "list_skills", return_value=sample_skills()):
            screen = SkillsScreen()
            app = DummyHostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press(*keys)
                await pilot.pause()
                yield app, screen, pilot

    async def test_empty_state(self):
        with patch.object(SkillManager, "list_skills", return_value=[]):
            screen = SkillsScreen()
            app = DummyHostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()
                opt_list = screen.query_one("#skills-option-list", OptionList)
                await pilot.press("escape")
                await pilot.pause()
                self.assertEqual(len(opt_list._options), 1)
                self.assertIn("No skills found", str(opt_list._options[0].prompt))
                self.assertIsNone(app.dismiss_result)

    async def test_load_skills_populates_options(self):
        async for app, screen, pilot in self._run():
            opt_list = screen.query_one("#skills-option-list", OptionList)
            prompts = [str(o.prompt) for o in opt_list._options]
            # Global header + reviewer, Project header + test-runner
            self.assertGreaterEqual(len(prompts), 4)
            self.assertTrue(any(p.strip() == "Global" for p in prompts))
            self.assertTrue(any(p.strip() == "Project" for p in prompts))
            self.assertTrue(any("VISIBLE" in p and "reviewer" in p for p in prompts))
            self.assertTrue(any("HIDDEN" in p and "test-runner" in p for p in prompts))
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsNone(app.dismiss_result)

    async def test_filter_match(self):
        async for app, screen, pilot in self._run("r", "e", "v"):
            skills = [s for s in screen.filtered_skills if s is not None]
            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0]["name"], "reviewer")
            opt_list = screen.query_one("#skills-option-list", OptionList)
            # First selectable row gets highlighted
            self.assertEqual(opt_list.highlighted, 1)

    async def test_filter_no_match(self):
        async for app, screen, pilot in self._run("z", "z", "z"):
            self.assertEqual(len([s for s in screen.filtered_skills if s is not None]), 0)
            opt_list = screen.query_one("#skills-option-list", OptionList)
            self.assertIn("No matching skills", str(opt_list._options[0].prompt))

    async def test_filter_matches_description_and_scope(self):
        # "suite" only in test-runner description, "pro" only in test-runner scope (project)
        for query in ("suite", "pro"):
            async for app, screen, pilot in self._run(*list(query)):
                skills = [s for s in screen.filtered_skills if s is not None]
                self.assertEqual(len(skills), 1)
                self.assertEqual(skills[0]["name"], "test-runner")

    async def test_on_input_submitted_highlighted_valid_dismisses_skill(self):
        async for app, screen, pilot in self._run():
            self.assertEqual(screen.query_one("#skills-option-list", OptionList).highlighted, 1)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsNotNone(app.dismiss_result)
            self.assertEqual(app.dismiss_result["name"], "reviewer")

    async def test_on_input_submitted_no_highlight_dismisses_none(self):
        async for app, screen, pilot in self._run():
            opt_list = screen.query_one("#skills-option-list", OptionList)
            opt_list.highlighted = None
            with patch.object(screen, "query_one", return_value=opt_list):
                screen.on_input_submitted(Input.Submitted(screen.query_one("#modal-search-input"), "x"))
            self.assertIsNone(app.dismiss_result)

    async def test_on_input_submitted_exception_dismisses_none(self):
        async for app, screen, pilot in self._run():
            with patch.object(screen, "query_one", side_effect=Exception("boom")):
                screen.on_input_submitted(Input.Submitted(Input(id="modal-search-input"), "x"))
            self.assertIsNone(app.dismiss_result)

    async def test_key_down_up_navigation(self):
        async for app, screen, pilot in self._run():
            opt_list = screen.query_one("#skills-option-list", OptionList)
            search_input = screen.query_one("#modal-search-input", Input)
            self.assertTrue(search_input.has_focus)
            # highlighted starts at 1 (first selectable row, GLOBAL header is 0)
            self.assertEqual(opt_list.highlighted, 1)
            # Down moves cursor to next selectable (skips disabled headers)
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(opt_list.highlighted, 4)
            # Down wraps around to first selectable
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(opt_list.highlighted, 1)
            # Up moves cursor backwards (skips disabled headers)
            await pilot.press("up")
            await pilot.pause()
            self.assertEqual(opt_list.highlighted, 4)

    async def test_key_navigation_from_none_highlight(self):
        async for app, screen, pilot in self._run():
            opt_list = screen.query_one("#skills-option-list", OptionList)
            opt_list.highlighted = None
            # Down with highlighted None initializes it to 0
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(opt_list.highlighted, 0)

    async def test_on_mount_focus_exception(self):
        # query_one raises for the search input inside on_mount; swallowed (lines 89-92)
        with patch.object(SkillManager, "list_skills", return_value=sample_skills()):
            screen = SkillsScreen()

            def raising_query_one(selector, expect_type=None):
                if selector == "#modal-search-input":
                    raise Exception("boom")
                return original_query_one(selector, expect_type)

            original_query_one = screen.query_one
            with patch.object(screen, "query_one", side_effect=raising_query_one):
                app = DummyHostApp(screen)
                async with app.run_test() as pilot:
                    await pilot.pause()
                    self.assertTrue(screen.is_mounted)

    async def test_key_navigation_exception(self):
        async for app, screen, pilot in self._run():
            with patch.object(screen, "query_one", side_effect=Exception("boom")):
                screen._on_key(Key("down", character=None))

    async def test_toggle_hidden(self):
        with patch.object(SkillManager, "toggle_hidden", return_value=True) as mock_toggle:
            async for app, screen, pilot in self._run():
                opt_list = screen.query_one("#skills-option-list", OptionList)
                self.assertEqual(opt_list.highlighted, 1)
                screen.action_toggle_hidden()
                mock_toggle.assert_called_once_with("reviewer")

    async def test_toggle_hidden_on_header_noop(self):
        async for app, screen, pilot in self._run():
            opt_list = screen.query_one("#skills-option-list", OptionList)
            opt_list.highlighted = 0
            with patch.object(SkillManager, "toggle_hidden") as mock_toggle:
                screen.action_toggle_hidden()
                mock_toggle.assert_not_called()

    async def test_toggle_hidden_exception(self):
        async for app, screen, pilot in self._run():
            with patch.object(screen, "query_one", side_effect=Exception("boom")):
                screen.action_toggle_hidden()

    async def test_apply_filter_no_skills_exception(self):
        async for app, screen, pilot in self._run():
            with patch.object(screen, "query_one", side_effect=Exception("boom")):
                screen._apply_filter()

    async def test_option_selected_valid_dismisses_skill(self):
        async for app, screen, pilot in self._run():
            opt_list = screen.query_one("#skills-option-list", OptionList)
            screen.on_option_list_option_selected(OptionList.OptionSelected(opt_list, Option("reviewer"), 1))
            await pilot.pause()
            self.assertEqual(app.dismiss_result["name"], "reviewer")

    async def test_option_selected_header_noop(self):
        async for app, screen, pilot in self._run():
            opt_list = screen.query_one("#skills-option-list", OptionList)
            screen.on_option_list_option_selected(OptionList.OptionSelected(opt_list, Option("GLOBAL"), 0))
            await pilot.pause()
            self.assertIsNone(app.dismiss_result)

    async def test_option_selected_invalid_dismisses_none(self):
        async for app, screen, pilot in self._run():
            opt_list = screen.query_one("#skills-option-list", OptionList)
            screen.on_option_list_option_selected(OptionList.OptionSelected(opt_list, Option("nope"), 99))
            await pilot.pause()
            self.assertIsNone(app.dismiss_result)

    async def test_action_quit_app(self):
        async for app, screen, pilot in self._run():
            with patch.object(screen.app, "exit") as mock_exit:
                screen.action_quit_app()
                mock_exit.assert_called_once()
            break


if __name__ == "__main__":
    unittest.main()
