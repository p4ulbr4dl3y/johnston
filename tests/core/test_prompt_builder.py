import unittest

from core.application.generation.prompt_builder import PromptBuilder


class TestPromptBuilder(unittest.TestCase):
    def test_build_system_prompt_default(self):
        builder = PromptBuilder("System prompt test", [], role="worker")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("System prompt test", sys_prompt)
        self.assertIn("<environment>", sys_prompt)
        self.assertIn("cwd:", sys_prompt)
        self.assertIn("date:", sys_prompt)
        self.assertIn("os:", sys_prompt)
        self.assertIn("sandbox: ", sys_prompt)
        self.assertIn('<role name="worker"', sys_prompt)

    def test_build_system_prompt_sandbox_states(self):
        b_on = PromptBuilder("Test", [], sandbox_enabled=True)
        self.assertIn("sandbox: active (fs write: cwd/tmp only, creds/keys blocked)", b_on.build_system_prompt())

        b_off = PromptBuilder("Test", [], sandbox_enabled=False)
        self.assertIn("sandbox: disabled", b_off.build_system_prompt())

    def test_build_system_prompt_explorer_mode(self):
        builder = PromptBuilder("System prompt test", [], role="explorer")
        sys_prompt = builder.build_system_prompt()
        self.assertIn('<role name="explorer"', sys_prompt)
        self.assertIn("Read-only", sys_prompt)
        self.assertIn("sandbox: active (fs write: cwd/tmp only, creds/keys blocked)", sys_prompt)

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

    def test_build_tools_properties_preserves_order_and_required_sorted(self):
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

        # Author's property order is preserved to assist model token generation
        self.assertEqual(prop_keys, ["z_param", "a_param", "m_param"])
        # Required list is sorted deterministically
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
        self.assertIn("sandbox: active (fs write: cwd/tmp only, creds/keys blocked)", prompt)

    def test_build_system_prompt_sandbox_disabled(self):
        builder = PromptBuilder("Test", [], role="worker", sandbox_enabled=False)
        prompt = builder.build_system_prompt()
        self.assertIn("sandbox: disabled", prompt)
        self.assertNotIn("sandbox: active", prompt)

    def test_build_system_prompt_subagent_worktree_guidelines(self):
        builder = PromptBuilder(
            "Subagent prompt",
            [],
            role="worker",
            is_subagent=True,
            worktree_branch="feature-x",
        )
        prompt = builder.build_system_prompt()
        self.assertIn("<worktree>", prompt)
        self.assertIn("Branch: `feature-x`", prompt)
        self.assertIn("Relative paths ONLY", prompt)
        self.assertIn("git checkout/switch", prompt)


    def test_build_system_prompt_all_instruction_formats(self):
        import os
        import tempfile

        from core.application.generation.prompt_builder import get_project_instruction_rules

        with tempfile.TemporaryDirectory() as tmp:
            # 1. .clinerules
            with open(os.path.join(tmp, ".clinerules"), "w", encoding="utf-8") as f:
                f.write("Cline rule content")

            # 2. .github/copilot-instructions.md
            gh_dir = os.path.join(tmp, ".github")
            os.makedirs(gh_dir, exist_ok=True)
            with open(os.path.join(gh_dir, "copilot-instructions.md"), "w", encoding="utf-8") as f:
                f.write("Copilot rule content")

            # 3. .cursor/rules/*.mdc
            cur_dir = os.path.join(tmp, ".cursor", "rules")
            os.makedirs(cur_dir, exist_ok=True)
            with open(os.path.join(cur_dir, "frontend.mdc"), "w", encoding="utf-8") as f:
                f.write("---\ndescription: Frontend rules\nglobs: *.tsx\n---\nCursor MDC rule content")

            rules = get_project_instruction_rules(cwd=tmp)
            rule_names = [r.name for r in rules]
            self.assertIn(".clinerules", rule_names)
            self.assertIn(os.path.join(".github", "copilot-instructions.md"), rule_names)
            self.assertIn(os.path.join(".cursor", "rules", "frontend.mdc"), rule_names)

            mdc_rule = next(r for r in rules if "frontend.mdc" in r.name)
            self.assertEqual(mdc_rule.content, "Cursor MDC rule content")


if __name__ == "__main__":
    unittest.main()

