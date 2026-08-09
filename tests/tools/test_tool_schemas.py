import os
import tempfile
import unittest

from tools.registry import TOOL_CLASSES, execute_tool, get_default_tools


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

    def test_shell_schema_documents_background_and_params(self):
        from tools.shell import ShellTool
        props = ShellTool.schema["function"]["parameters"]["properties"]
        self.assertNotIn("skip_confirm", props)
        self.assertNotIn("no_background", props)

    def test_manage_task_action_has_enum_and_required(self):
        from tools.manage_task import ManageTaskTool
        params = ManageTaskTool.schema["function"]["parameters"]
        self.assertEqual(
            params["properties"]["action"]["enum"],
            ["list", "status", "kill", "send_input"],
        )
        self.assertIn("action", params["required"])

    def test_subagent_schema_has_session_id(self):
        from tools.invoke_subagent import InvokeSubagentTool
        props = InvokeSubagentTool.schema["function"]["parameters"]["properties"]
        self.assertIn("session_id", props)
        self.assertNotIn("task_id", props)

    def test_manage_subagent_schema_has_session_id(self):
        from tools.manage_subagent import ManageSubagentTool
        props = ManageSubagentTool.schema["function"]["parameters"]["properties"]
        self.assertIn("session_id", props)
        self.assertNotIn("task_id", props)


class TestToolRegistryRegression(unittest.IsolatedAsyncioTestCase):
    async def test_execute_tool_resolves_file_aliases(self):
        fd, path = tempfile.mkstemp(dir=os.getcwd())
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("alias read content")

            res = await execute_tool("read_file", {"path": path})
            self.assertIn("alias read content", res)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    async def test_execute_tool_unknown_tool_is_reported(self):
        res = await execute_tool("xyz_unknown_tool_123", {})
        self.assertEqual(res, "ERR: unknown tool 'xyz_unknown_tool_123'")


if __name__ == "__main__":
    unittest.main()
