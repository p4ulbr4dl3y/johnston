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

    def test_manage_shell_action_has_enum_and_required(self):
        from tools.manage_shell import ManageShellTool

        params = ManageShellTool.schema["function"]["parameters"]
        self.assertEqual(
            params["properties"]["action"]["enum"],
            ["list", "send_input", "kill"],
        )
        self.assertIn("action", params["required"])

    def test_invoke_subagent_dynamic_role_enum(self):
        from tools.invoke_subagent import InvokeSubagentTool

        tool = InvokeSubagentTool()
        schema = tool.get_schema()
        type_prop = schema["function"]["parameters"]["properties"]["type"]
        self.assertIn("enum", type_prop)
        self.assertIn("worker", type_prop["enum"])
        self.assertIn("explorer", type_prop["enum"])

    def test_read_content_offset_schema(self):
        from tools.read import ReadTool

        props = ReadTool.schema["function"]["parameters"]["properties"]
        self.assertIn("content_offset", props)
        self.assertIn("offset", props["content_offset"]["description"].lower())
        self.assertNotIn("detail", props)

    def test_manage_shell_schema(self):
        from tools.manage_shell import ManageShellTool

        props = ManageShellTool.schema["function"]["parameters"]["properties"]
        self.assertIn("action", props)
        self.assertIn("task_id", props)
        self.assertIn("input", props)
        self.assertEqual(ManageShellTool.schema["function"]["parameters"]["required"], ["action"])

    def test_subagent_schema_has_title_and_branch_and_no_session_id(self):
        from tools.invoke_subagent import InvokeSubagentTool

        props = InvokeSubagentTool.schema["function"]["parameters"]["properties"]
        self.assertIn("title", props)
        self.assertNotIn("description", props)
        self.assertIn("title", InvokeSubagentTool.schema["function"]["parameters"]["required"])
        self.assertIn("branch", props)
        self.assertNotIn("branch", InvokeSubagentTool.schema["function"]["parameters"]["required"])
        self.assertNotIn("session_id", props)
        self.assertNotIn("task_id", props)

    def test_manage_subagent_schema_has_session_id(self):
        from tools.manage_subagent import ManageSubagentTool

        props = ManageSubagentTool.schema["function"]["parameters"]["properties"]
        self.assertIn("session_id", props)
        self.assertNotIn("task_id", props)


class TestToolRegistryRegression(unittest.IsolatedAsyncioTestCase):
    async def test_execute_tool_read_by_canonical_name(self):
        from core.permission_manager import PermissionManager

        PermissionManager.get_instance().set_session_override("read", "allow")
        fd, path = tempfile.mkstemp(dir=os.getcwd())
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("canonical read content")

            res = await execute_tool("read", {"path": path})
            self.assertIn("canonical read content", res.content)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    async def test_execute_tool_unknown_tool_is_reported(self):
        res = await execute_tool("xyz_unknown_tool_123", {})
        self.assertEqual(res.content, "ERR: unknown 'xyz_unknown_tool_123'")
        self.assertTrue(res.is_error)


if __name__ == "__main__":
    unittest.main()
