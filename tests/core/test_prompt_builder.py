import unittest

from core.application.generation.prompt_builder import PromptBuilder


class TestPromptBuilder(unittest.TestCase):
    def test_build_system_prompt_default(self):
        builder = PromptBuilder("System prompt test", [], role="worker")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("System prompt test", sys_prompt)
        self.assertIn("<environment", sys_prompt)
        self.assertIn('cwd="', sys_prompt)
        self.assertIn('date="', sys_prompt)
        self.assertIn('os="', sys_prompt)
        self.assertIn('<role name="worker"', sys_prompt)

    def test_build_system_prompt_explorer_mode(self):
        builder = PromptBuilder("System prompt test", [], role="explorer")
        sys_prompt = builder.build_system_prompt()
        self.assertIn('<role name="explorer"', sys_prompt)
        self.assertIn("Read-Only", sys_prompt)

    def test_build_tools_explorer_mode_filters_create_edit(self):
        builder = PromptBuilder(
            "System prompt test",
            [],
            role="explorer",
            subagent_schema={"type": "function", "function": {"name": "invoke_subagent"}},
        )
        tools = builder.build_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertNotIn("create", names)
        self.assertNotIn("edit", names)
        self.assertIn("invoke_subagent", names)

    def test_build_tools_sorted_alphabetically(self):
        base_tools = [
            {"function": {"name": "z_tool"}},
            {"function": {"name": "a_tool"}},
            {"function": {"name": "m_tool"}},
        ]
        builder = PromptBuilder("Test", base_tools, role="worker", allow_task=False)
        tools = builder.build_tools()
        names = [t.get("function", {}).get("name") for t in tools]
        self.assertEqual(names, sorted(names))

    def test_build_tools_properties_and_required_sorted_deterministically(self):
        base_tools = [
            {
                "type": "function",
                "function": {
                    "name": "complex_tool",
                    "description": "Test tool schema sorting",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "z_param": {"type": "string"},
                            "a_param": {"type": "number"},
                            "m_param": {"type": "boolean"},
                        },
                        "required": ["z_param", "a_param", "m_param"],
                    },
                },
            }
        ]
        builder = PromptBuilder("Test", base_tools, role="worker", allow_task=False)
        tools = builder.build_tools()
        params = tools[0]["function"]["parameters"]
        prop_keys = list(params["properties"].keys())
        req_keys = params["required"]

        self.assertEqual(prop_keys, ["a_param", "m_param", "z_param"])
        self.assertEqual(req_keys, ["a_param", "m_param", "z_param"])

    def test_build_system_prompt_includes_project_instructions(self):
        builder = PromptBuilder("System prompt test", [], role="worker")
        sys_prompt = builder.build_system_prompt()
        self.assertIn('<rule id="project:AGENTS.md">', sys_prompt)

    def test_build_system_prompt_explorer_filters_write_tools(self):
        pb_exp = PromptBuilder(
            "System prompt test",
            [{"function": {"name": "read"}}, {"function": {"name": "create"}}, {"function": {"name": "edit"}}],
            role="explorer",
        )
        prompt_exp = pb_exp.build_system_prompt()
        tools_exp = pb_exp.build_tools()
        exp_tool_names = [t["function"]["name"] for t in tools_exp]
        self.assertIn('<role name="explorer"', prompt_exp)
        self.assertNotIn("create", exp_tool_names)
        self.assertNotIn("edit", exp_tool_names)
        self.assertIn("read", exp_tool_names)

    def test_build_system_prompt_includes_user_rules(self):
        import os
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = os.path.join(tmpdir, ".johnston", "rules")
            os.makedirs(rules_dir)
            with open(os.path.join(rules_dir, "custom_rule.md"), "w") as f:
                f.write("Always use pytest")

            with patch("os.getcwd", return_value=tmpdir):
                builder = PromptBuilder("Test", [], role="worker")
                prompt = builder.build_system_prompt()
                self.assertIn("<user_rules>", prompt)
                self.assertIn('<rule id="project:custom_rule">', prompt)
                self.assertIn("Always use pytest", prompt)

    def test_build_system_prompt_env_metadata_last(self):
        # Volatile env metadata must come AFTER the stable base + mode block so
        # the stable prefix is prompt-cacheable across turns.
        builder = PromptBuilder("Base instructions marker", [], role="worker")
        prompt = builder.build_system_prompt()
        self.assertLess(prompt.index("Base instructions marker"), prompt.index("<environment"))
        self.assertLess(prompt.index('<role name="worker"'), prompt.index("<environment"))

    def test_build_system_prompt_substitutes_model_name(self):
        builder = PromptBuilder(
            "You are {model_name} operating inside Johnston CLI", [], role="worker", model_name="Gemini 3.6 Flash"
        )
        prompt = builder.build_system_prompt()
        self.assertIn("You are Gemini 3.6 Flash operating inside Johnston CLI", prompt)

    def test_build_system_prompt_fallback_model_name(self):
        builder = PromptBuilder("You are {model_name} operating inside Johnston CLI", [], role="worker", model_name="")
        prompt = builder.build_system_prompt()
        self.assertIn("You are an expert AI assistant operating inside Johnston CLI", prompt)

    def test_build_system_prompt_orchestrator_as_subagent_no_prompt(self):
        builder = PromptBuilder("Subagent base prompt", [], role="orchestrator", is_subagent=True)
        prompt = builder.build_system_prompt()
        self.assertIn("Subagent base prompt", prompt)
        self.assertNotIn('<role name="orchestrator"', prompt)
        self.assertNotIn("<subagents>", prompt)
        self.assertIn("<environment", prompt)

    def test_build_tools_subagent_hardens_shell(self):
        from tools.shell import ShellTool

        builder = PromptBuilder("Test", [ShellTool().schema], role="worker", is_subagent=True)
        tools = builder.build_tools()
        shell = next((t for t in tools if t.get("function", {}).get("name") == "shell"), None)
        self.assertIsNotNone(shell)
        props = shell["function"]["parameters"]["properties"]
        self.assertNotIn("background", props)
        self.assertIn("synchronous", shell["function"]["description"].lower())

    def test_build_system_prompt_sandbox_active(self):
        builder = PromptBuilder("Test", [], role="worker", sandbox_enabled=True)
        prompt = builder.build_system_prompt()
        self.assertIn('sandbox="active"', prompt)

    def test_build_system_prompt_sandbox_disabled(self):
        builder = PromptBuilder("Test", [], role="worker", sandbox_enabled=False)
        prompt = builder.build_system_prompt()
        self.assertNotIn('sandbox="active"', prompt)

    def test_build_system_prompt_subagent_worktree_guidelines(self):
        builder = PromptBuilder(
            "Subagent prompt",
            [],
            role="worker",
            is_subagent=True,
            worktree_branch="feature-x",
        )
        prompt = builder.build_system_prompt()
        self.assertIn("<worktree_guidelines>", prompt)
        self.assertIn("branch 'feature-x'", prompt)
        self.assertIn("NEVER modify files in parent repository paths", prompt)
        self.assertIn("DO NOT switch branches", prompt)


if __name__ == "__main__":
    unittest.main()

