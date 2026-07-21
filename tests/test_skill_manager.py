import os
import shutil
import tempfile
import unittest

from core.skill_manager import SkillManager, parse_frontmatter
from tools.skill import SkillTool


class TestSkillManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_parse_frontmatter(self):
        content = "---\nname: my-skill\ndescription: A cool skill\n---\n# Title\nBody text"
        fm, body = parse_frontmatter(content)
        self.assertEqual(fm["name"], "my-skill")
        self.assertEqual(fm["description"], "A cool skill")
        self.assertIn("# Title", body)

    def test_global_and_project_skills(self):
        sm = SkillManager(project_dir=self.test_dir)

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
        names = [s["name"] for s in skills]
        self.assertIn("code-reviewer", names)
        self.assertIn("custom-test", names)

        # Test loading payload
        payload = sm.load_skill_payload("code-reviewer")
        self.assertIn('<skill_content name="code-reviewer">', payload)
        self.assertIn("<file>script.py</file>", payload)

    async def test_skill_tool_execution(self):
        sm = SkillManager(project_dir=self.test_dir)
        p_skill_dir = os.path.join(sm.project_dir_skills, "linter")
        os.makedirs(p_skill_dir, exist_ok=True)
        with open(os.path.join(p_skill_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: linter\ndescription: Project linter\n---\nLint instructions.")

        tool = SkillTool()
        res = await tool.execute({"name": "linter"})
        self.assertIn('<skill_content name="linter">', res)
        self.assertIn("Lint instructions.", res)

        res_missing = await tool.execute({"name": "nonexistent"})
        self.assertIn("Error: Unable to load skill", res_missing)

    def test_skills_command_registered(self):
        from commands import COMMAND_REGISTRY
        self.assertIn("/skills", COMMAND_REGISTRY)

if __name__ == "__main__":
    unittest.main()
