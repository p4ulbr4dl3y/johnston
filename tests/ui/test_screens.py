import unittest
from unittest.mock import MagicMock, patch

from widgets.screens.ask_user import ConfirmScreen
from widgets.screens.base_selection import BaseSelectionScreen
from widgets.screens.help import HelpScreen
from widgets.screens.providers import ApiKeyInputScreen, ProvidersScreen
from widgets.screens.resume import ResumeScreen
from widgets.screens.tasks import TaskConsoleScreen, TasksListScreen


class TestConfirmScreen(unittest.TestCase):
    def test_init(self):
        self.assertEqual(ConfirmScreen("Summary text").summary, "Summary text")

    def test_bindings(self):
        keys = [b[0] for b in ConfirmScreen("x").BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("enter", keys)


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


class TestTaskScreens(unittest.TestCase):
    def test_console_init(self):
        mock_task = MagicMock()
        mock_task.command = "npm run dev"
        s = TaskConsoleScreen(mock_task)
        self.assertEqual(s.bg_task, mock_task)
        self.assertEqual(s.printed_count, 0)

    def test_console_bindings(self):
        keys = [b[0] for b in TaskConsoleScreen(MagicMock()).BINDINGS]
        self.assertIn("escape", keys)

    def test_list_bindings(self):
        keys = [b[0] for b in TasksListScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("tab", keys)


class TestMCPScreen(unittest.TestCase):
    @patch("widgets.screens.mcp.get_mcp_manager")
    def test_init(self, mock_get_mgr):
        mock_mgr = MagicMock()
        mock_get_mgr.return_value = mock_mgr
        from widgets.screens.mcp import MCPScreen

        s = MCPScreen()
        self.assertEqual(s.servers, [])
        self.assertEqual(s.mm, mock_mgr)

    def test_bindings(self):
        from widgets.screens.mcp import MCPScreen

        keys = [b[0] for b in MCPScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("tab", keys)


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
        from unittest.mock import MagicMock

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


class TestSkillScreens(unittest.TestCase):
    @patch("widgets.screens.skills.SkillManager")
    def test_detail_init(self, _):
        from widgets.screens.skills import SkillDetailScreen

        skill = {"name": "my-skill", "description": "Does things", "scope": "project"}
        s = SkillDetailScreen(skill)
        self.assertEqual(s.skill, skill)

    @patch("widgets.screens.skills.SkillManager")
    def test_detail_bindings(self, _):
        from widgets.screens.skills import SkillDetailScreen

        keys = [b[0] for b in SkillDetailScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("enter", keys)

    @patch("widgets.screens.skills.SkillManager")
    def test_list_init_with_skills(self, mock_sm_cls):
        mock_sm = MagicMock()
        mock_sm.list_skills.return_value = [
            {"name": "skill-a", "scope": "global"},
            {"name": "skill-b", "scope": "project"},
        ]
        mock_sm_cls.return_value = mock_sm
        from widgets.screens.skills import SkillsScreen

        s = SkillsScreen()
        self.assertEqual(len(s.options), 2)
        self.assertIn("GLOBAL", s.options[0])
        self.assertIn("PROJECT", s.options[1])

    @patch("widgets.screens.skills.SkillManager")
    def test_list_init_no_skills(self, mock_sm_cls):
        mock_sm = MagicMock()
        mock_sm.list_skills.return_value = []
        mock_sm_cls.return_value = mock_sm
        from widgets.screens.skills import SkillsScreen

        s = SkillsScreen()
        self.assertEqual(s.options, [])

    @patch("widgets.screens.skills.SkillManager")
    def test_skills_screen_toggle_hidden(self, mock_sm_cls):
        mock_sm = MagicMock()
        mock_sm.list_skills.return_value = [{"name": "skill-a", "scope": "global", "hidden": True}]
        mock_sm.toggle_hidden.return_value = False
        mock_sm_cls.return_value = mock_sm
        from widgets.screens.skills import SkillsScreen

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
