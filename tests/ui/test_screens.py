import unittest
from unittest.mock import MagicMock, patch

from textual.events import Key

from core.application.session.actions import RewindEntry
from core.application.skills.manager import Skill, SkillScope
from widgets.presentation.screens.ask_user import ConfirmScreen
from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.help import HelpScreen
from widgets.presentation.screens.providers import ApiKeyInputScreen, ProvidersScreen
from widgets.presentation.screens.resume import ResumeScreen
from widgets.presentation.screens.rewind import RewindScreen
from widgets.presentation.screens.tasks import ShellTasksScreen, SubagentsScreen, TaskConsoleScreen


class TestConfirmScreen(unittest.TestCase):
    def test_init(self):
        self.assertEqual(ConfirmScreen("Summary text").summary, "Summary text")

    def test_bindings(self):
        keys = [b[0] for b in ConfirmScreen("x").BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("enter", keys)


class TestConfirmCancelPath(unittest.TestCase):
    def test_confirm_cancel_dismisses_cancelled(self):
        s = ConfirmScreen("summary")
        with patch.object(s, "dismiss") as dismiss:
            s._mount_time = 0  # old mount => bypass debounce
            s.action_cancel()
        dismiss.assert_called_once_with("cancelled")

    def test_confirm_enter_debounced_bypass(self):
        s = ConfirmScreen("summary")
        with patch.object(s, "dismiss") as dismiss:
            s._mount_time = 0
            s.action_confirm()
        dismiss.assert_called_once_with("confirm")


class TestHelpScreen(unittest.TestCase):
    def test_init(self):
        self.assertEqual(HelpScreen().active_tab, 0)

    def test_bindings(self):
        keys = [b[0] for b in HelpScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("enter", keys)


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
        self.assertIn("[dim][5 steps][/dim]", s.raw_options[0])
        self.assertEqual(s.raw_items, ["s1", "s2"])
        self.assertEqual(s.default_value, "s1")

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
        self.assertEqual(len(s.raw_items), 1)

    def test_empty_message_uses_placeholder(self):
        s = RewindScreen([RewindEntry(0, "")])
        self.assertIn("(empty message)", s.raw_options[0])


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
        self.assertIn("k", keys)

    def test_shell_bindings(self):
        keys = [b[0] for b in ShellTasksScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("k", keys)


class TestProvidersScreen(unittest.TestCase):
    def test_build_options_status_tags(self):
        providers = {
            "active": {"key": "active", "name": "ActiveProv"},
            "off": {"key": "off", "name": "OffProv", "disabled": True},
            "auth": {"key": "auth", "name": "AuthProv"},
            "on": {"key": "on", "name": "OnProv"},
        }
        s = ProvidersScreen(
            providers=providers, active_key="active", configured_keys={"on": "key"}, disabled_providers=["off"]
        )
        opts, items = s.raw_options, s.raw_items
        self.assertEqual(items, ["active", "off", "auth", "on"])
        self.assertIn("ACTIVE", next(o for o, i in zip(opts, items) if i == "active"))
        self.assertIn("OFF", next(o for o, i in zip(opts, items) if i == "off"))
        self.assertIn("AUTH", next(o for o, i in zip(opts, items) if i == "auth"))
        self.assertIn("ON", next(o for o, i in zip(opts, items) if i == "on"))

    def test_provider_without_key_shows_auth(self):
        s = ProvidersScreen(
            providers={"custom": {"key": "custom", "name": "Custom"}}, active_key="", configured_keys={}
        )
        self.assertIn("AUTH", s.raw_options[0])

    def test_default_falls_back_to_first(self):
        s = ProvidersScreen(providers={"p1": {"key": "p1", "name": "P1"}}, active_key="nope", configured_keys={})
        self.assertEqual(s.default_value, "p1")

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


class TestApiKeyInputScreen(unittest.TestCase):
    def test_init_with_key(self):
        s = ApiKeyInputScreen("MyProvider", "myprov", "sk-abcdefghij123456")
        self.assertEqual(s.provider_name, "MyProvider")
        self.assertEqual(s.current_key, "sk-abcdefghij123456")

    def test_init_without_key(self):
        s = ApiKeyInputScreen("NewProvider", "newprov", "")
        self.assertEqual(s.current_key, "")

    def test_bindings(self):
        keys = [b[0] for b in ApiKeyInputScreen.BINDINGS]
        self.assertIn("escape", keys)

    def test_blocks_shift_tab(self):
        screen = ApiKeyInputScreen(provider_name="Test", provider_key="test")

        for key_name in ("shift+tab", "backtab", "shift_tab"):
            event = Key(key=key_name, character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()

            screen._on_key(event)

            event.prevent_default.assert_called_once()
            event.stop.assert_called_once()


class TestSkillScreens(unittest.TestCase):
    @patch("widgets.presentation.screens.skills.SkillManager")
    def test_detail_init(self, _):
        from widgets.presentation.screens.skills import SkillDetailScreen

        skill = {"name": "my-skill", "description": "Does things", "scope": "project"}
        s = SkillDetailScreen(skill)
        self.assertEqual(s.skill, skill)

    @patch("widgets.presentation.screens.skills.SkillManager")
    def test_detail_bindings(self, _):
        from widgets.presentation.screens.skills import SkillDetailScreen

        keys = [b[0] for b in SkillDetailScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("enter", keys)

    @patch("widgets.presentation.screens.skills.SkillManager")
    def test_list_init_with_skills(self, mock_sm_cls):
        mock_sm = MagicMock()
        mock_sm.list_skills.return_value = [
            Skill("skill-a", "", "", "", SkillScope.GLOBAL, False),
            Skill("skill-b", "", "", "", SkillScope.PROJECT, False),
        ]
        mock_sm_cls.return_value = mock_sm
        from widgets.presentation.screens.skills import SkillsScreen

        s = SkillsScreen()
        self.assertEqual(len(s.options), 2)
        self.assertIn("skill-a", s.options[0])
        self.assertIn("VISIBLE", s.options[0])
        self.assertIn("skill-b", s.options[1])
        self.assertIn("VISIBLE", s.options[1])

    @patch("widgets.presentation.screens.skills.SkillManager")
    def test_list_init_no_skills(self, mock_sm_cls):
        mock_sm = MagicMock()
        mock_sm.list_skills.return_value = []
        mock_sm_cls.return_value = mock_sm
        from widgets.presentation.screens.skills import SkillsScreen

        s = SkillsScreen()
        self.assertEqual(s.options, [])

    @patch("widgets.presentation.screens.skills.SkillManager")
    def test_skills_screen_toggle_hidden(self, mock_sm_cls):
        mock_sm = MagicMock()
        mock_sm.list_skills.return_value = [Skill("skill-a", "", "", "", SkillScope.GLOBAL, True)]
        mock_sm.toggle_hidden.return_value = False
        mock_sm_cls.return_value = mock_sm
        from widgets.presentation.screens.skills import SkillsScreen

        s = SkillsScreen()
        self.assertEqual(len(s.options), 1)
        self.assertIn("[HIDDEN]", s.options[0])

        s.query_one = MagicMock()
        mock_opt_list = MagicMock()
        mock_opt_list.highlighted = 0
        s.query_one.return_value = mock_opt_list

        s.action_toggle_hidden()
        mock_sm.toggle_hidden.assert_called_once_with("skill-a")


if __name__ == "__main__":
    unittest.main()
