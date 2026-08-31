import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from textual.events import Key

from core.application.session.actions import RewindEntry
from core.application.skills.manager import Skill, SkillScope
from widgets.presentation.screens.base_selection import BaseSelectionScreen, HeaderWrapOptionList
from widgets.presentation.screens.help import HelpScreen
from widgets.presentation.screens.providers import ProvidersScreen
from widgets.presentation.screens.resume import ResumeScreen
from widgets.presentation.screens.rewind import RewindScreen
from widgets.presentation.screens.tasks import ShellTasksScreen, SubagentsScreen, TaskConsoleScreen


class TestHelpScreen(unittest.TestCase):
    def test_init(self):
        self.assertEqual(HelpScreen().active_tab, 0)

    def test_bindings(self):
        keys = [b[0] for b in HelpScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("enter", keys)

    def test_on_click_tab_switch(self):
        s = HelpScreen()
        s._refresh_view = MagicMock()

        # Click on keybindings tab
        target_keys = MagicMock()
        target_keys.id = "help-tab-keybindings"
        event_keys = MagicMock()
        event_keys.widget = target_keys

        s.on_click(event_keys)
        self.assertEqual(s.active_tab, 1)
        s._refresh_view.assert_called_once()
        event_keys.stop.assert_called_once()

        # Click on commands tab
        s._refresh_view.reset_mock()
        target_cmd = MagicMock()
        target_cmd.id = "help-tab-commands"
        event_cmd = MagicMock()
        event_cmd.widget = target_cmd

        s.on_click(event_cmd)
        self.assertEqual(s.active_tab, 0)
        s._refresh_view.assert_called_once()
        event_cmd.stop.assert_called_once()



class TestResumeScreen(unittest.TestCase):
    def test_init_with_sessions(self):
        sessions = [
            {"id": "s1", "title": "First session", "message_count": 5},
            {"id": "s2", "title": "Second\nmultiline\rsession", "message_count": 10},
        ]
        s = ResumeScreen(sessions)
        self.assertEqual(len(s.raw_options), 2)
        self.assertNotIn("\n", s.raw_options[1])
        self.assertIn("Second multiline session", s.raw_options[1])
        self.assertIn("5 steps", s.raw_options[0])
        self.assertEqual(s.raw_items, ["s1", "s2"])
        self.assertEqual(s.default_value, "s1")

    def test_init_with_active_session(self):
        sessions = [
            {"id": "s1", "title": "First session", "message_count": 5},
            {"id": "s2", "title": "Second session", "message_count": 10},
        ]
        s = ResumeScreen(sessions, current_session_id="s2")
        self.assertNotIn("●", s.raw_options[0])
        self.assertIn("● Second session", s.raw_options[1])
        self.assertEqual(s.default_value, "s2")

    def test_init_empty(self):
        s = ResumeScreen([])
        self.assertEqual(s.raw_options, [])
        self.assertEqual(s.default_value, "")


class TestResumeEdge(unittest.TestCase):
    def test_session_missing_id_uses_gettext(self):
        """Sessions without 'id' (malformed payload) must not raise KeyError."""
        try:
            s = ResumeScreen([{"title": "T", "message_count": 2}])
        except KeyError as exc:
            self.fail(f"missing id raised KeyError: {exc}")
        self.assertEqual(len(s.raw_items), 1)

    def test_empty_title_and_zero_count(self):
        s = ResumeScreen([{"id": "s1", "title": "", "message_count": 0}])
        self.assertEqual(len(s.raw_options), 1)


class TestRewindEdge(unittest.TestCase):
    def test_short_rewind_entry_index(self):
        """A RewindEntry is the structured input; no malformed-tuple handling."""
        try:
            s = RewindScreen([RewindEntry(1, "")])
        except IndexError as exc:
            self.fail(f"single RewindEntry raised IndexError: {exc}")
        self.assertEqual(len(s.raw_items), 2)

    def test_empty_message_uses_placeholder(self):
        s = RewindScreen([RewindEntry(0, "")])
        self.assertIn("(empty message)", s.raw_options[0])

    def test_long_message_truncated(self):
        long_text = "A" * 100
        s = RewindScreen([RewindEntry(0, long_text)])
        self.assertIn("...", s.raw_options[0])
        self.assertTrue(s.raw_options[0].startswith("A" * 50))


class TestBaseSelectionScreen(unittest.TestCase):
    def test_init(self):
        s = BaseSelectionScreen("### Pick", ["A", "B", "C"], ["a", "b", "c"], "b")
        self.assertEqual(s.raw_options, ["A", "B", "C"])
        self.assertEqual(s.raw_items, ["a", "b", "c"])
        self.assertEqual(s.default_value, "b")
        self.assertFalse(s.show_search)

    def test_init_with_search(self):
        s = BaseSelectionScreen("t", ["X"], ["x"], "x", show_search=True, search_placeholder="Find...")
        self.assertTrue(s.show_search)


class TestModalSearchShiftTab(unittest.TestCase):
    def test_base_selection_screen_blocks_shift_tab_when_search_enabled(self):
        screen = BaseSelectionScreen(
            title="Test", options=["Opt1", "Opt2"], items=["item1", "item2"], default_value="item1", show_search=True
        )

        for key_name in ("shift+tab", "backtab", "shift_tab"):
            event = Key(key=key_name, character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()

            screen._on_key(event)

            event.prevent_default.assert_called_once()
            event.stop.assert_called_once()

    def test_base_selection_screen_allows_other_keys(self):
        screen = BaseSelectionScreen(
            title="Test", options=["Opt1", "Opt2"], items=["item1", "item2"], default_value="item1", show_search=True
        )

        event = Key(key="a", character="a")
        event.prevent_default = MagicMock()
        event.stop = MagicMock()

        screen._on_key(event)

        event.prevent_default.assert_not_called()
        event.stop.assert_not_called()


class TestHeaderWrapOptionList(unittest.TestCase):
    def test_mouse_move_updates_highlighted(self):
        from rich.style import Style
        from textual.widgets.option_list import Option

        opt_list = HeaderWrapOptionList(
            Option("Disabled Header", disabled=True),
            Option("Option 1"),
            Option("Option 2"),
        )
        opt_list.highlighted = 1

        # Hover over Option 2 (index 2)
        mock_event = MagicMock()
        mock_event.style = Style(meta={"option": 2})
        opt_list._on_mouse_move(mock_event)
        self.assertEqual(opt_list.highlighted, 2)

        # Hover over Disabled Header (index 0) - should NOT change highlighted
        mock_event.style = Style(meta={"option": 0})
        opt_list._on_mouse_move(mock_event)
        self.assertEqual(opt_list.highlighted, 2)

        # Hover over no option
        mock_event.style = Style(meta={})
        opt_list._on_mouse_move(mock_event)
        self.assertEqual(opt_list.highlighted, 2)



class TestTaskScreens(unittest.TestCase):
    def test_console_init(self):
        mock_task = MagicMock()
        mock_task.command = "npm run dev"
        s = TaskConsoleScreen(mock_task)
        self.assertEqual(s.bg_task, mock_task)
        self.assertEqual(s._pending_line, "")

    def test_console_bindings(self):
        s = TaskConsoleScreen(MagicMock())
        keys = [b[0] for b in s.BINDINGS]
        self.assertIn("escape", keys)
        # No polling interval remains.
        self.assertEqual(len(s._timers), 0)

    def test_subagents_bindings(self):
        keys = [b[0] for b in SubagentsScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("ctrl+k", keys)

    def test_shell_bindings(self):
        keys = [b[0] for b in ShellTasksScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("ctrl+k", keys)

    def test_shell_tasks_screen_empty_dismisses(self):
        s = ShellTasksScreen()
        s.dismiss = MagicMock()
        mock_opt = MagicMock()
        with patch.object(ShellTasksScreen, "is_mounted", new_callable=PropertyMock, return_value=True), \
             patch.object(s, "_get_filtered_tasks", return_value=[]), \
             patch.object(s, "query_one", return_value=mock_opt):
            s.update_tasks_list()
            s.dismiss.assert_called_once()
            self.assertEqual(s.filtered_tasks, [])

    def test_subagents_screen_empty_dismisses(self):
        s = SubagentsScreen()
        s.dismiss = MagicMock()
        mock_opt = MagicMock()
        with patch.object(SubagentsScreen, "is_mounted", new_callable=PropertyMock, return_value=True), \
             patch.object(s, "_get_filtered_tasks", return_value=[]), \
             patch.object(s, "_get_option_list", return_value=mock_opt):
            s.update_tasks_list()
            s.dismiss.assert_called_once()
            self.assertEqual(s.filtered_tasks, [])

    def test_subagents_screen_sync_listeners_and_unmount(self):
        s = SubagentsScreen()
        sess1 = MagicMock()
        sess2 = MagicMock()
        s._sync_session_listeners([sess1, sess2])
        sess1.add_listener.assert_called_once_with(s._on_session_event)
        sess2.add_listener.assert_called_once_with(s._on_session_event)
        self.assertEqual(s._observed_sessions, {sess1, sess2})

        # syncing again does not re-add
        s._sync_session_listeners([sess1])
        self.assertEqual(sess1.add_listener.call_count, 1)

        # unmount detaches all
        s.on_unmount()
        sess1.remove_listener.assert_called_once_with(s._on_session_event)
        sess2.remove_listener.assert_called_once_with(s._on_session_event)
        self.assertEqual(s._observed_sessions, set())

    def test_subagents_screen_on_session_event_invalidates_and_updates(self):
        s = SubagentsScreen()
        s._tasks_cache_ts = 123.45
        mock_app = MagicMock()
        s.update_tasks_list = MagicMock()
        with patch.object(SubagentsScreen, "is_mounted", new_callable=PropertyMock, return_value=True), \
             patch.object(SubagentsScreen, "app", new_callable=PropertyMock, return_value=mock_app):
            s._on_session_event({"type": "tool"})
            self.assertIsNone(s._tasks_cache_ts)
            mock_app.call_from_thread.assert_called_once_with(s.update_tasks_list)

    def test_base_modal_screen_dismiss_safety(self):
        from widgets.presentation.screens.base_modal import BaseModalScreen

        screen = BaseModalScreen()
        mock_app = MagicMock()
        mock_app._screen_stack = [MagicMock()]  # only base screen
        screen._app = mock_app

        # Should not raise ScreenStackError when stack has only 1 screen
        screen.dismiss()
        self.assertFalse(getattr(screen, "_is_dismissed", False))

        # When screen is in stack
        mock_app._screen_stack = [mock_app._screen_stack[0], screen]
        screen.dismiss()
        self.assertTrue(getattr(screen, "_is_dismissed", False))

        # Subsequent calls are ignored
        screen.dismiss()

    def test_shell_tasks_screen_kill_task_dismiss_guard(self):
        import asyncio

        s = ShellTasksScreen()
        s.filtered_tasks = [{"id": "1", "raw_obj": MagicMock()}]
        mock_opt = MagicMock()
        mock_opt.highlighted = 0
        s._get_option_list = MagicMock(return_value=mock_opt)

        async def fake_kill(item):
            s._is_dismissed = True

        s._kill_item = fake_kill
        s.update_tasks_list = MagicMock()

        with patch.object(ShellTasksScreen, "is_mounted", new_callable=PropertyMock, return_value=True):
            asyncio.run(s.action_kill_task())
            s.update_tasks_list.assert_not_called()

    def test_tasks_screen_search_and_nav(self):
        from textual.widgets import Input

        s = ShellTasksScreen()
        mock_task1 = MagicMock()
        mock_task1.is_background = True
        mock_task1.is_running = True
        mock_task1.task_id = "task-1"
        mock_task1.kind = "shell"
        mock_task1.command = "pytest tests"
        mock_task1.session_id = "sess-1"

        mock_task2 = MagicMock()
        mock_task2.is_background = True
        mock_task2.is_running = False
        mock_task2.task_id = "task-2"
        mock_task2.kind = "shell"
        mock_task2.command = "ruff check"
        mock_task2.session_id = "sess-1"

        mock_app = MagicMock()
        mock_app.task_manager = [mock_task1, mock_task2]
        mock_app.current_session_id = "sess-1"

        with patch.object(ShellTasksScreen, "app", new_callable=PropertyMock, return_value=mock_app):
            tasks = s._get_filtered_tasks()
            self.assertEqual(len(tasks), 2)

            # Test search filter
            s.search_query = "ruff"
            filtered = s._get_filtered_tasks()
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["id"], "task-2")

        # Test input changed
        s.update_tasks_list = MagicMock()
        s.on_input_changed(Input.Changed(Input(), "pytest"))
        self.assertEqual(s.search_query, "pytest")
        s.update_tasks_list.assert_called_once()

        # Test tab key suppression
        tab_event = MagicMock()
        tab_event.key = "tab"
        s._on_key(tab_event)
        tab_event.prevent_default.assert_called_once()
        tab_event.stop.assert_called_once()




class TestProvidersScreen(unittest.TestCase):
    def test_build_options_status_tags(self):
        providers = {
            "active": {"key": "active", "name": "ActiveProv"},
            "off": {"key": "off", "name": "OffProv", "enabled": False},
            "auth": {"key": "auth", "name": "AuthProv"},
            "on": {"key": "on", "name": "OnProv"},
        }
        s = ProvidersScreen(
            providers=providers, active_key="active", configured_keys={"on": "key"}, disabled_providers=["off"]
        )
        opts, items = s.raw_options, s.raw_items
        self.assertEqual(items, ["active", "off", "auth", "on"])
        self.assertIn("●", next(o for o, i in zip(opts, items) if i == "active"))
        self.assertIn("○", next(o for o, i in zip(opts, items) if i == "off"))
        self.assertNotIn("●", next(o for o, i in zip(opts, items) if i == "auth"))
        self.assertIn("●", next(o for o, i in zip(opts, items) if i == "on"))

    def test_provider_without_key_shows_auth(self):
        s = ProvidersScreen(
            providers={"custom": {"key": "custom", "name": "Custom"}}, active_key="", configured_keys={}
        )
        self.assertNotIn("●", s.raw_options[0])

    def test_default_falls_back_to_first(self):
        s = ProvidersScreen(providers={"p1": {"key": "p1", "name": "P1"}}, active_key="nope", configured_keys={})
        self.assertEqual(s.default_value, "p1")

    def test_provider_model_count_badge(self):
        providers = {
            "p1": {"key": "p1", "name": "P1", "models": ["m1", "m2"]},
            "p2": {"key": "p2", "name": "P2", "models": ["m3"]},
            "p3": {"key": "p3", "name": "P3", "models": ["m4"]},
        }
        s = ProvidersScreen(
            providers=providers,
            active_key="p1",
            configured_keys={"p2": "key"},
            disabled_providers=["p3"],
        )
        self.assertIn("2 models", s.raw_options[0])
        self.assertIn("1 model", s.raw_options[1])
        self.assertNotIn("model", s.raw_options[2])  # p3 is disabled/off

    def test_tab_key_toggles_disabled(self):
        providers = {"p1": {"key": "p1", "name": "P1"}}
        pm = MagicMock()
        s = ProvidersScreen(providers=providers, active_key="p1", configured_keys={}, pm=pm)
        # Mock query_one and event
        opt_list = MagicMock()
        opt_list.highlighted = 0
        search_input = MagicMock()
        search_input.value = ""
        s.query_one = MagicMock(
            side_effect=lambda id_name, *args: opt_list if "option-list" in id_name else search_input
        )
        event = MagicMock(key="tab")
        s._on_key(event)
        self.assertIn("p1", s.disabled_set)
        pm.set_provider_disabled.assert_called_with("p1", True)
        event.prevent_default.assert_called_once()
        event.stop.assert_called_once()

    def test_step_transitions_and_esc_back(self):
        from widgets.presentation.screens.api_key import ApiKeyScreen

        providers = {"p1": {"key": "p1", "name": "P1"}}
        s = ProvidersScreen(providers=providers, active_key="", configured_keys={"p1": "secret-key"})
        dismissed = []
        s.dismiss = lambda val: dismissed.append(val)

        mock_app = MagicMock()
        with patch.object(ProvidersScreen, "app", new=mock_app):
            # Select AUTH option -> pushes ApiKeyScreen
            mock_ev = MagicMock()
            mock_ev.option_index = 0
            s.on_option_list_option_selected(mock_ev)
            mock_app.push_screen.assert_called_once()

            args, kwargs = mock_app.push_screen.call_args
            key_screen = args[0]
            cb = kwargs.get("callback")
            self.assertIsInstance(key_screen, ApiKeyScreen)
            self.assertEqual(key_screen.provider_name, "P1")
            self.assertEqual(key_screen.current_key, "secret-key")

            # Callback with key dismisses ProvidersScreen
            cb("new-key")
            self.assertEqual(dismissed, [("p1", "new-key")])

        # Action cancel dismisses None
        s.action_cancel()
        self.assertEqual(dismissed, [("p1", "new-key"), None])

    def test_api_key_screen_input_submission(self):
        from widgets.presentation.screens.api_key import ApiKeyScreen

        s = ApiKeyScreen(provider_name="P1", current_key="existing-key", provider_key="p1")
        dismissed = []
        s.dismiss = lambda val: dismissed.append(val)

        submit_ev = MagicMock()
        submit_ev.value = "my-new-key"
        s.on_input_submitted(submit_ev)
        self.assertEqual(dismissed, ["my-new-key"])

        # Test empty input keeps existing key
        dismissed.clear()
        submit_ev.value = ""
        s.on_input_submitted(submit_ev)
        self.assertEqual(dismissed, ["existing-key"])

        # Cancel dismisses None
        dismissed.clear()
        s.action_cancel()
        self.assertEqual(dismissed, [None])


class TestProvidersEdge(unittest.TestCase):
    def test_provider_missing_key_uses_get(self):
        """Provider dicts missing 'key' (malformed payload) must not raise KeyError."""
        try:
            s = ProvidersScreen({"p1": {"name": "P1"}}, "p1", {})
        except KeyError as exc:
            self.fail(f"missing key raised KeyError: {exc}")
        self.assertEqual(s.raw_items, ["p1"])

    def test_provider_target_is_none_value(self):
        """A provider value that is None (malformed payload) must not raise
        AttributeError during option building."""
        try:
            s = ProvidersScreen({"p1": None}, "", {})
        except (KeyError, AttributeError, TypeError) as exc:
            self.fail(f"None provider value raised {type(exc).__name__}: {exc}")
        self.assertEqual(s.raw_items, [])


class TestSkillScreens(unittest.TestCase):
    @patch("widgets.presentation.screens.skills.get_skill_manager")
    def test_list_init_with_skills(self, mock_get_sm):
        mock_sm = MagicMock()
        mock_sm.list_skills.return_value = [
            Skill("skill-a", "", "", "", SkillScope.GLOBAL, False),
            Skill("skill-b", "", "", "", SkillScope.PROJECT, False),
        ]
        mock_get_sm.return_value = mock_sm
        from widgets.presentation.screens.skills import SkillsScreen

        s = SkillsScreen()
        self.assertEqual(len(s.options), 2)
        self.assertIn("skill-a", s.options[0])
        self.assertIn("●", s.options[0])
        self.assertIn("skill-b", s.options[1])
        self.assertIn("●", s.options[1])

    @patch("widgets.presentation.screens.skills.get_skill_manager")
    def test_list_init_no_skills(self, mock_get_sm):
        mock_sm = MagicMock()
        mock_sm.list_skills.return_value = []
        mock_get_sm.return_value = mock_sm
        from widgets.presentation.screens.skills import SkillsScreen

        s = SkillsScreen()
        self.assertEqual(s.options, [])

    @patch("widgets.presentation.screens.skills.get_skill_manager")
    def test_skills_screen_toggle_hidden(self, mock_get_sm):
        mock_sm = MagicMock()
        mock_sm.list_skills.return_value = [Skill("skill-a", "", "", "", SkillScope.GLOBAL, True)]
        mock_sm.toggle_hidden.return_value = False
        mock_get_sm.return_value = mock_sm
        from widgets.presentation.screens.skills import SkillsScreen

        s = SkillsScreen()
        self.assertEqual(len(s.options), 1)
        self.assertIn("○", s.options[0])

        s.query_one = MagicMock()
        mock_opt_list = MagicMock()
        mock_opt_list.highlighted = 0
        s.query_one.return_value = mock_opt_list

        s.action_toggle_hidden()
        mock_sm.toggle_hidden.assert_called_once_with("skill-a")


if __name__ == "__main__":
    unittest.main()
