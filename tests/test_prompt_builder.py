import unittest

from core.prompt_builder import PromptBuilder


class TestPromptBuilder(unittest.TestCase):
    def test_build_system_prompt_default(self):
        builder = PromptBuilder("System prompt test", [], mode="build")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("System prompt test", sys_prompt)

    def test_build_system_prompt_plan_mode(self):
        builder = PromptBuilder("System prompt test", [], mode="plan")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("[PLAN MODE ACTIVE]", sys_prompt)
        self.assertIn("PlanExit", sys_prompt)

    def test_build_tools_adds_task_and_plan_exit(self):
        builder = PromptBuilder("System prompt test", [], mode="plan")
        tools = builder.build_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn("PlanExit", names)
        self.assertIn("Task", names)

    def test_build_tools_build_mode_no_plan_exit(self):
        builder = PromptBuilder("System prompt test", [], mode="build")
        tools = builder.build_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertNotIn("PlanExit", names)
        self.assertIn("Task", names)

if __name__ == "__main__":
    unittest.main()
