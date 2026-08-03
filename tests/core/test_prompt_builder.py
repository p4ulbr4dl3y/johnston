import unittest

from core.prompt_builder import PromptBuilder


class TestPromptBuilder(unittest.TestCase):
    def test_build_system_prompt_default(self):
        builder = PromptBuilder("System prompt test", [], mode="action")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("System prompt test", sys_prompt)
        self.assertIn("## Environment Metadata", sys_prompt)
        self.assertIn("- Working Directory:", sys_prompt)
        self.assertIn("- Local Time:", sys_prompt)
        self.assertIn("- Operating System:", sys_prompt)
        self.assertIn("## Execution Mode: ACTION", sys_prompt)

    def test_build_system_prompt_explore_mode(self):
        builder = PromptBuilder("System prompt test", [], mode="explore")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("## Execution Mode: EXPLORE", sys_prompt)
        self.assertIn("Shift+Tab or /action", sys_prompt)

    def test_build_tools_explore_mode_filters_create_edit(self):
        builder = PromptBuilder("System prompt test", [], mode="explore")
        tools = builder.build_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertNotIn("create", names)
        self.assertNotIn("edit", names)
        self.assertIn("invoke_subagent", names)

    def test_build_system_prompt_includes_project_instructions(self):
        builder = PromptBuilder("System prompt test", [], mode="action")
        sys_prompt = builder.build_system_prompt()
        self.assertIn("## Project Instructions", sys_prompt)

    def test_build_system_prompt_explore_filters_write_tools(self):
        pb_exp = PromptBuilder(
            "System prompt test",
            [{"function": {"name": "read"}}, {"function": {"name": "create"}}, {"function": {"name": "edit"}}],
            mode="explore"
        )
        prompt_exp = pb_exp.build_system_prompt()
        tools_exp = pb_exp.build_tools()
        exp_tool_names = [t["function"]["name"] for t in tools_exp]
        self.assertIn("## Execution Mode: EXPLORE", prompt_exp)
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
                builder = PromptBuilder("Test", [], mode="action")
                prompt = builder.build_system_prompt()
                self.assertIn("## User Rules", prompt)
                self.assertIn("### Rule: custom_rule", prompt)
                self.assertIn("Always use pytest", prompt)

    def test_build_system_prompt_env_metadata_last(self):
        # Volatile env metadata must come AFTER the stable base + mode block so
        # the stable prefix is prompt-cacheable across turns.
        builder = PromptBuilder("Base instructions marker", [], mode="action")
        prompt = builder.build_system_prompt()
        self.assertLess(prompt.index("Base instructions marker"), prompt.index("## Environment Metadata"))
        self.assertLess(prompt.index("## Execution Mode: ACTION"), prompt.index("## Environment Metadata"))

    def test_build_system_prompt_cached_within_ttl(self):
        import time as _time
        from unittest.mock import patch

        import core.prompt_builder as pb
        pb._SYSTEM_PROMPT_CACHE.clear()
        builder = PromptBuilder("Cache stability marker", [], mode="action")
        first = builder.build_system_prompt()
        # Rebuild "later" but still inside the TTL window: must return the exact
        # same cached string (env time frozen) instead of recomputing.
        with patch("core.prompt_builder.time.time", return_value=_time.time() + 1):
            second = builder.build_system_prompt()
        self.assertEqual(first, second)
        self.assertIn("Cache stability marker", first)
        self.assertGreaterEqual(len(pb._SYSTEM_PROMPT_CACHE), 1)

    def test_build_system_prompt_cache_invalidates_on_mode_change(self):
        import core.prompt_builder as pb
        pb._SYSTEM_PROMPT_CACHE.clear()
        action_prompt = PromptBuilder("Mode invalidate marker", [], mode="action").build_system_prompt()
        explore_prompt = PromptBuilder("Mode invalidate marker", [], mode="explore").build_system_prompt()
        # Different mode -> different cache key -> rebuilt with the explore block
        self.assertIn("## Execution Mode: ACTION", action_prompt)
        self.assertIn("## Execution Mode: EXPLORE", explore_prompt)
    def test_build_system_prompt_substitutes_model_name(self):
        builder = PromptBuilder("You are {model_name} operating inside Johnston CLI", [], mode="action", model_name="Gemini 3.6 Flash")
        prompt = builder.build_system_prompt()
        self.assertIn("You are Gemini 3.6 Flash operating inside Johnston CLI", prompt)

    def test_build_system_prompt_fallback_model_name(self):
        builder = PromptBuilder("You are {model_name} operating inside Johnston CLI", [], mode="action", model_name="")
        prompt = builder.build_system_prompt()
        self.assertIn("You are an expert AI software engineer operating inside Johnston CLI", prompt)


if __name__ == "__main__":
    unittest.main()
