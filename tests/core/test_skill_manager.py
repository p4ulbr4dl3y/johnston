import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.application.skills.manager import SkillManager, get_skill_manager, reset_skill_managers
from core.infrastructure.runtime.frontmatter import parse_frontmatter


class TestSkillManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_skill_managers()
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        reset_skill_managers()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_parse_frontmatter(self):
        content = "---\nname: my-skill\ndescription: A cool skill\n---\n# Title\nBody text"
        fm, body = parse_frontmatter(content)
        self.assertEqual(fm["name"], "my-skill")
        self.assertEqual(fm["description"], "A cool skill")
        self.assertIn("# Title", body)

        content_multiline = "---\nname: caveman\ndescription: >\n  Ultra-compressed mode.\n  Cuts tokens.\n---\nBody"
        fm2, _ = parse_frontmatter(content_multiline)
        self.assertEqual(fm2["name"], "caveman")
        self.assertEqual(fm2["description"], "Ultra-compressed mode. Cuts tokens.")

    def test_global_and_project_skills(self):
        sm = SkillManager(project_dir=self.test_dir)
        global_tmp = tempfile.mkdtemp()
        sm.global_dir = global_tmp

        try:
            # Global skill
            g_skill_dir = os.path.join(sm.global_dir, "code-reviewer")
            os.makedirs(g_skill_dir, exist_ok=True)
            with open(os.path.join(g_skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: code-reviewer\ndescription: Global reviewer\n---\nReview code.")
            with open(os.path.join(g_skill_dir, "script.py"), "w") as f:
                f.write("print('hello')")

            # Project skill
            p_skill_dir = os.path.join(sm.project_dir_skills, "custom-test")
            os.makedirs(p_skill_dir, exist_ok=True)
            with open(os.path.join(p_skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: custom-test\ndescription: Project test skill\n---\nRun tests.")

            skills = sm.list_skills()
            names = [s.name for s in skills]
            self.assertIn("code-reviewer", names)
            self.assertIn("custom-test", names)
        finally:
            shutil.rmtree(global_tmp)

    def test_matching_global_and_project_dir_scope(self):
        sm = SkillManager(project_dir=self.test_dir)
        sm.global_dir = sm.project_dir_skills

        g_skill_dir = os.path.join(sm.global_dir, "home-skill")
        os.makedirs(g_skill_dir, exist_ok=True)
        with open(os.path.join(g_skill_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: home-skill\ndescription: Home skill\n---\nHome body.")

        skills = sm.list_skills()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].scope.value, "global")

    def test_hidden_skills(self):
        sm = SkillManager(project_dir=self.test_dir)
        p_skill_dir = os.path.join(sm.project_dir_skills, "secret-skill")
        os.makedirs(p_skill_dir, exist_ok=True)
        with open(os.path.join(p_skill_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: secret-skill\ndescription: Hidden skill\nhidden: true\n---\nSecret body.")

        # By default list_skills includes hidden skills for UI
        ui_names = [s.name for s in sm.list_skills(include_hidden=True)]
        self.assertIn("secret-skill", ui_names)

        # for_system_prompt=True excludes hidden skills
        prompt_names = [s.name for s in sm.list_skills(include_hidden=False, for_system_prompt=True)]
        self.assertNotIn("secret-skill", prompt_names)

        # get_skill loads secret-skill by default
        hidden_skill = sm.get_skill("secret-skill")
        self.assertIsNotNone(hidden_skill)
        self.assertEqual(hidden_skill.name, "secret-skill")

        # Test toggle_hidden
        new_hidden_state = sm.toggle_hidden("secret-skill")
        self.assertFalse(new_hidden_state)
        updated_skill = sm.get_skill("secret-skill")
        self.assertFalse(updated_skill.hidden)

        # Toggle back to hidden
        re_hidden_state = sm.toggle_hidden("secret-skill")
        self.assertTrue(re_hidden_state)

    def test_skills_command_registered(self):
        from widgets.app.dispatch import COMMAND_REGISTRY

        self.assertIn("/skills", COMMAND_REGISTRY)

    def test_skill_command_suggestions(self):
        from widgets.app.command_provider import get_all_command_suggestions

        async def run():
            return await get_all_command_suggestions()

        import asyncio

        suggestions = asyncio.run(run())
        cmd_names = [name for name, _ in suggestions]
        self.assertIn("/skills", cmd_names)
        self.assertIn("/johnston-guide", cmd_names)

    def test_johnston_guide_references_created(self):
        sm = get_skill_manager()
        guide_dir = os.path.join(sm.global_dir, "johnston-guide")
        self.assertTrue(os.path.exists(os.path.join(guide_dir, "SKILL.md")))
        self.assertTrue(os.path.exists(os.path.join(guide_dir, "references", "cli_flags.md")))
        self.assertTrue(os.path.exists(os.path.join(guide_dir, "references", "mcp.md")))
        self.assertTrue(os.path.exists(os.path.join(guide_dir, "references", "roles.md")))

    def test_nested_reference_md_ignored_as_skill(self):
        sm = SkillManager(project_dir=self.test_dir)
        p_skill_dir = os.path.join(sm.project_dir_skills, "complex-skill")
        os.makedirs(os.path.join(p_skill_dir, "references"), exist_ok=True)
        with open(os.path.join(p_skill_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: complex-skill\ndescription: Main skill\n---\nMain body.")
        with open(os.path.join(p_skill_dir, "references", "helper.md"), "w") as f:
            f.write("---\nname: helper\ndescription: Helper doc\n---\nHelper body.")

        skill_names = [s.name for s in sm.list_skills(include_hidden=True)]
        self.assertIn("complex-skill", skill_names)
        self.assertNotIn("helper", skill_names)

    async def test_skill_slash_command_execution(self):
        from widgets.app.dispatch import handle_slash_command

        try:
            from tests.core.test_commands import MockApp
        except ImportError:
            from tests.ui.test_commands import MockApp

        os.chdir(self.old_cwd)
        reset_skill_managers()
        app = MockApp()
        handled = await handle_slash_command(app, "/johnston-guide configure MCP")
        self.assertTrue(handled)
        self.assertEqual(len(app.ai_prompts), 1)
        self.assertIn("johnston-guide", app.ai_prompts[0][0])
        self.assertIn("configure MCP", app.ai_prompts[0][0])

    async def test_multi_skill_slash_command_execution(self):
        from widgets.app.dispatch import handle_slash_command

        try:
            from tests.core.test_commands import MockApp
        except ImportError:
            from tests.ui.test_commands import MockApp

        os.chdir(self.old_cwd)
        reset_skill_managers()
        app = MockApp()
        handled = await handle_slash_command(app, "/johnston-guide /caveman refactor code")
        self.assertTrue(handled)
        self.assertEqual(len(app.ai_prompts), 1)
        self.assertIn("johnston-guide", app.ai_prompts[0][0])
        self.assertIn("caveman", app.ai_prompts[0][0])
        self.assertIn("refactor code", app.ai_prompts[0][0])

    def test_list_skills_ttl_cache_skips_signature_scan(self):
        from unittest.mock import patch

        sm = SkillManager(project_dir=self.test_dir)
        sm.list_skills()
        with patch.object(sm, "_compute_scan_signature", side_effect=AssertionError("Should not compute signature within TTL")):
            # Within TTL window, calling list_skills() must use cached result without computing signature
            skills = sm.list_skills()
            self.assertIsInstance(skills, list)

    def test_get_skill_manager_shares_instance_per_project_dir(self):
        sm1 = get_skill_manager(self.old_cwd)
        sm2 = get_skill_manager(self.old_cwd)
        self.assertIs(sm1, sm2)

        other_dir = tempfile.mkdtemp()
        try:
            sm_other = get_skill_manager(other_dir)
            self.assertIsNot(sm1, sm_other)
            self.assertEqual(sm_other.project_dir, os.path.realpath(other_dir))
        finally:
            shutil.rmtree(other_dir)

    def test_skill_manager_construction_has_no_side_effects(self):
        with patch("core.application.skills.manager.os.makedirs") as mock_makedirs:
            SkillManager(project_dir=self.test_dir)
        mock_makedirs.assert_not_called()

    def test_get_skill_manager_provisions_bundled_skill(self):
        reset_skill_managers()
        with patch(
            "core.application.skills.manager.GLOBAL_SKILLS_DIR",
            os.path.join(self.test_dir, "global-skills"),
        ):
            get_skill_manager()
            guide_md = os.path.join(self.test_dir, "global-skills", "johnston-guide", "SKILL.md")
            self.assertTrue(os.path.exists(guide_md))
            # Second call must not re-provision (flag set), and returns the cached manager.
            sm_cached = get_skill_manager()
            self.assertIs(get_skill_manager(), sm_cached)

    def test_toggle_hidden_unknown_skill_raises_key_error(self):
        sm = SkillManager(project_dir=self.test_dir)
        with self.assertRaises(KeyError):
            sm.toggle_hidden("no-such-skill")


if __name__ == "__main__":
    unittest.main()
