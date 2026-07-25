import unittest

from tools.registry import TOOL_CLASSES, get_default_tools


class TestToolSchemas(unittest.TestCase):
    """Production guards: tool descriptions are single-sourced and schema-complete."""

    def test_all_tools_have_synced_description(self):
        for cls in TOOL_CLASSES:
            self.assertTrue(cls.description, f"{cls.name} missing class description")
            self.assertEqual(
                cls.schema["function"]["description"],
                cls.description,
                f"{cls.name} schema description desynced from class description",
            )

    def test_default_tools_all_carry_descriptions(self):
        for t in get_default_tools():
            self.assertTrue(
                t["function"].get("description"),
                f"{t['function']['name']} missing schema description",
            )

    def test_bash_schema_documents_background_and_params(self):
        from tools.bash import BashTool
        props = BashTool.schema["function"]["parameters"]["properties"]
        self.assertIn("skip_confirm", props)
        self.assertIn("no_background", props)
        self.assertIn("10 seconds", BashTool.schema["function"]["description"])

    def test_manage_task_action_has_enum_and_required(self):
        from tools.manage_task import ManageTaskTool
        params = ManageTaskTool.schema["function"]["parameters"]
        self.assertEqual(
            params["properties"]["action"]["enum"],
            ["list", "status", "kill", "send_input"],
        )
        self.assertIn("action", params["required"])

    def test_subagent_schema_has_task_id(self):
        from tools.subagent import SubagentTool
        props = SubagentTool.schema["function"]["parameters"]["properties"]
        self.assertIn("task_id", props)


if __name__ == "__main__":
    unittest.main()
