import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.models_catalog import catalog
from widgets.screens.ask_user import ConfirmScreen, QuestionScreen
from widgets.screens.base_selection import BaseSelectionScreen
from widgets.screens.help import HelpScreen
from widgets.screens.model import ModelScreen, VisionWarningScreen
from widgets.screens.providers import ApiKeyInputScreen, ProvidersScreen
from widgets.screens.resume import ResumeScreen
from widgets.screens.tasks import TaskConsoleScreen, TasksListScreen


class TestQuestionScreen(unittest.TestCase):
    def test_init_with_options(self):
        s = QuestionScreen("### **Q 1/2**", "Pick a color", ["red", "blue"], "red")
        self.assertEqual(s.num_text, "### **Q 1/2**")
        self.assertEqual(s.question_text, "Pick a color")
        self.assertEqual(s.raw_options, ["red", "blue"])
        self.assertIn("Write-in...", s.options)
        self.assertEqual(s.current_val, "red")

    def test_init_without_options(self):
        s = QuestionScreen("### **Q 1/1**", "Type answer", [])
        self.assertEqual(s.raw_options, [])
        self.assertEqual(s.options, [])

    def test_bindings(self):
        keys = [b[0] for b in QuestionScreen("n", "q", ["a"]).BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("left", keys)


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
        self.assertIn("\\[5 msgs]", s.raw_options[0])
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
        self.assertIn("k", keys)


class TestMCPScreen(unittest.TestCase):
    @patch("widgets.screens.mcp.MCPManager")
    def test_init(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr
        from widgets.screens.mcp import MCPScreen
        s = MCPScreen()
        self.assertEqual(s.servers, [])
        self.assertEqual(s.mm, mock_mgr)

    def test_bindings(self):
        from widgets.screens.mcp import MCPScreen
        keys = [b[0] for b in MCPScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("m", keys)


class TestProvidersScreen(unittest.TestCase):
    def test_build_options_status_tags(self):
        providers = {
            "active": {"key": "active", "name": "ActiveProv"},
            "off": {"key": "off", "name": "OffProv", "disabled": True},
            "auth": {"key": "auth", "name": "AuthProv"},
            "on": {"key": "on", "name": "OnProv"},
        }
        s = ProvidersScreen(providers=providers, active_key="active", configured_keys={"on": "key"}, disabled_providers=["off"])
        opts, items = s.raw_options, s.raw_items
        self.assertEqual(items, ["active", "off", "auth", "on"])
        self.assertIn("ACTIVE", next(o for o, i in zip(opts, items) if i == "active"))
        self.assertIn("OFF", next(o for o, i in zip(opts, items) if i == "off"))
        self.assertIn("AUTH", next(o for o, i in zip(opts, items) if i == "auth"))
        self.assertIn("ON", next(o for o, i in zip(opts, items) if i == "on"))

    def test_opencode_shows_on_without_key(self):
        s = ProvidersScreen(providers={"opencode": {"key": "opencode", "name": "OpenCode"}}, active_key="", configured_keys={})
        self.assertIn("ON", s.raw_options[0])

    def test_default_falls_back_to_first(self):
        s = ProvidersScreen(providers={"p1": {"key": "p1", "name": "P1"}}, active_key="nope", configured_keys={})
        self.assertEqual(s.default_value, "p1")


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
        mock_sm.list_skills.return_value = [{"name": "skill-a", "scope": "global"}, {"name": "skill-b", "scope": "project"}]
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


class TestSubagentsScreen(unittest.TestCase):
    def setUp(self):
        from core.subagent_tracker import SUBAGENTS_DIR, SubagentTracker
        self.old_dir = SUBAGENTS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tracker = SubagentTracker.get_instance()
        self.tracker.storage_dir = self.temp_dir.name
        self.tracker.sessions.clear()

    def tearDown(self):
        for sess in list(self.tracker.sessions.values()):
            if sess.async_task and not sess.async_task.done():
                sess.async_task.cancel()
        self.tracker.sessions.clear()
        self.tracker.storage_dir = self.old_dir

    def test_init(self):
        from widgets.screens.subagents import SubagentsScreen
        s = SubagentsScreen()
        self.assertEqual(s.sessions, [])

    def test_bindings(self):
        from widgets.screens.subagents import SubagentsScreen
        keys = [b[0] for b in SubagentsScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("k", keys)


class TestModelScreen(unittest.TestCase):
    def test_header_title_all_tab(self):
        self.assertIn("All Models", ModelScreen._get_header_title_text("all"))

    def test_header_title_vision_tab(self):
        self.assertIn("Vision Models", ModelScreen._get_header_title_text("vision"))

    def test_build_data_list_format(self):
        s = ModelScreen(models_data=["model-a", "model-b"], current_model="model-a", current_provider="tp")
        self.assertIn("model-a", s.raw_items)
        self.assertEqual(s.default_value, "model-a")
        self.assertTrue(any("[ACTIVE]" in opt for opt in s.raw_options if isinstance(opt, str)))

    def test_build_data_dict_format(self):
        models_data = {"prov1": {"name": "P1", "models": ["m1", "m2"]}, "prov2": {"name": "P2", "models": ["m3"]}}
        s = ModelScreen(models_data=models_data, current_model="m2", current_provider="prov1")
        tuple_items = [i for i in s.raw_items if isinstance(i, tuple)]
        self.assertTrue(len(tuple_items) >= 3)
        self.assertEqual(s.default_value[0], "prov1")
        self.assertEqual(s.default_value[1], "m2")
        self.assertTrue(any("[ACTIVE]" in opt for opt in s.raw_options if isinstance(opt, str)))

    def test_build_data_vision_tab_active(self):
        models_data = {"prov1": {"name": "P1", "models": ["m1", "m2"]}}
        with patch.object(catalog, "save_cache"):
            catalog.add_vision_override("m1")
            s = ModelScreen(models_data=models_data, current_model="m1", current_provider="prov1", initial_tab="vision")
            self.assertTrue(any("[ACTIVE]" in opt for opt in s.raw_options if isinstance(opt, str)))
            catalog.remove_vision_override("m1")


class TestVisionWarningScreen(unittest.TestCase):
    def test_init(self):
        s = VisionWarningScreen("gpt-3.5", "OpenAI")
        self.assertEqual(s.model_name, "gpt-3.5")
        self.assertEqual(s.provider_name, "OpenAI")

    def test_bindings(self):
        keys = [b[0] for b in VisionWarningScreen.BINDINGS]
        self.assertIn("escape", keys)

    def test_options(self):
        with patch.object(catalog, "save_cache"):
            catalog.set_fallback_vision_model("", "")
            s1 = VisionWarningScreen("gpt-3.5", "OpenAI")
            self.assertEqual(s1.raw_items, ["select_vision", "force_vision"])

            catalog.set_fallback_vision_model("prov1", "vision-1")
            s2 = VisionWarningScreen("gpt-3.5", "OpenAI")
            self.assertEqual(s2.raw_items, ["select_vision", "use_fallback", "force_vision"])
            catalog.set_fallback_vision_model("", "")


class TestPolicyScreen(unittest.TestCase):
    def test_header_title(self):
        from widgets.screens.policy import PolicyScreen
        self.assertIn("Rules & Permissions", PolicyScreen._get_header_title_text("rules"))
        self.assertIn("Resource Budgets", PolicyScreen._get_header_title_text("budgets"))

    def test_build_data_rules_and_budgets(self):
        from widgets.screens.policy import PolicyScreen
        s = PolicyScreen(initial_tab="rules")
        opts_rules, items_rules = s._build_data("rules")
        self.assertTrue(len(opts_rules) > 0)
        self.assertEqual(len(opts_rules), len(items_rules))

        opts_budgets, items_budgets = s._build_data("budgets")
        self.assertTrue(len(opts_budgets) > 0)
        self.assertEqual(len(opts_budgets), len(items_budgets))

    def test_bindings(self):
        from widgets.screens.policy import PolicyScreen
        keys = [b[0] for b in PolicyScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("a", keys)
        self.assertIn("s", keys)
        self.assertIn("b", keys)


if __name__ == "__main__":
    unittest.main()

