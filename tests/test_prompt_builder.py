import unittest

from core.prompt_builder import PromptBuilder


class TestPromptBuilder(unittest.TestCase):
    def test_build_system_prompt_default(self):
        builder = PromptBuilder("System prompt test", [], mode="build")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("System prompt test", sys_prompt)
        self.assertIn("Environment Metadata:", sys_prompt)
        self.assertIn("Working Directory:", sys_prompt)
        self.assertIn("Local Time:", sys_prompt)
        self.assertIn("Operating System:", sys_prompt)

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
        self.assertIn("Subagent", names)

    def test_build_tools_build_mode_no_plan_exit(self):
        builder = PromptBuilder("System prompt test", [], mode="build")
        tools = builder.build_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertNotIn("PlanExit", names)
        self.assertIn("Subagent", names)

    def test_build_system_prompt_includes_project_instructions(self):
        builder = PromptBuilder("System prompt test", [], mode="build")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("[PROJECT INSTRUCTIONS (AGENTS.md)]", sys_prompt)

    def test_build_system_prompt_new_modes(self):
        # Ask mode
        pb_ask = PromptBuilder("System prompt test", [{"function": {"name": "Read"}}, {"function": {"name": "Create"}}, {"function": {"name": "Edit"}}], mode="ask")
        prompt_ask = pb_ask.build_system_prompt()
        tools_ask = pb_ask.build_tools()
        ask_tool_names = [t["function"]["name"] for t in tools_ask]
        self.assertIn("[ASK MODE ACTIVE - READ-ONLY ASSISTANT]", prompt_ask)
        self.assertNotIn("Create", ask_tool_names)
        self.assertNotIn("Edit", ask_tool_names)
        self.assertIn("Read", ask_tool_names)

        # Debug mode
        pb_debug = PromptBuilder("System prompt test", [], mode="debug")
        prompt_debug = pb_debug.build_system_prompt()
        self.assertIn("[DEBUG MODE ACTIVE - SYSTEMATIC DEBUGGER]", prompt_debug)

        # Orchestrator mode
        pb_orch = PromptBuilder("System prompt test", [], mode="orchestrator")
        prompt_orch = pb_orch.build_system_prompt()
        self.assertIn("[ORCHESTRATOR MODE ACTIVE - WORKFLOW COORDINATOR]", prompt_orch)

if __name__ == "__main__":
    unittest.main()
