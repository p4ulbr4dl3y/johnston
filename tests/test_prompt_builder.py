import unittest

from core.prompt_builder import PromptBuilder


class TestPromptBuilder(unittest.TestCase):
    def test_build_system_prompt_default(self):
        builder = PromptBuilder("System prompt test", [], mode="action")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("System prompt test", sys_prompt)
        self.assertIn("Environment Metadata:", sys_prompt)
        self.assertIn("Working Directory:", sys_prompt)
        self.assertIn("Local Time:", sys_prompt)
        self.assertIn("Operating System:", sys_prompt)
        self.assertIn("[MODE: ACTION]", sys_prompt)

    def test_build_system_prompt_explore_mode(self):
        builder = PromptBuilder("System prompt test", [], mode="explore")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("[MODE: EXPLORE]", sys_prompt)
        self.assertIn("SwitchToAction", sys_prompt)

    def test_build_tools_adds_task_and_switch_to_action(self):
        builder = PromptBuilder("System prompt test", [], mode="explore")
        tools = builder.build_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn("SwitchToAction", names)
        self.assertIn("Subagent", names)

    def test_build_tools_action_mode_no_switch_to_action(self):
        builder = PromptBuilder("System prompt test", [], mode="action")
        tools = builder.build_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertNotIn("SwitchToAction", names)
        self.assertIn("Subagent", names)

    def test_build_system_prompt_includes_project_instructions(self):
        builder = PromptBuilder("System prompt test", [], mode="action")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("[PROJECT INSTRUCTIONS (AGENTS.md)]", sys_prompt)

    def test_build_system_prompt_explore_filters_write_tools(self):
        pb_exp = PromptBuilder(
            "System prompt test",
            [{"function": {"name": "Read"}}, {"function": {"name": "Create"}}, {"function": {"name": "Edit"}}],
            mode="explore"
        )
        prompt_exp = pb_exp.build_system_prompt()
        tools_exp = pb_exp.build_tools()
        exp_tool_names = [t["function"]["name"] for t in tools_exp]
        self.assertIn("[MODE: EXPLORE]", prompt_exp)
        self.assertNotIn("Create", exp_tool_names)
        self.assertNotIn("Edit", exp_tool_names)
        self.assertIn("Read", exp_tool_names)


if __name__ == "__main__":
    unittest.main()
