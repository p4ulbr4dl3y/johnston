import os
import tempfile
import unittest

from core.role_registry import AgentRole, RoleRegistry, role_tool_error


class TestRoleRegistry(unittest.TestCase):
    def test_builtin_roles(self):
        reg = RoleRegistry.get_instance()
        roles = reg.load_roles(include_global=False)

        self.assertIn("act", roles)
        self.assertIn("explore", roles)
        self.assertIn("orchestrate", roles)
        self.assertIn("worker", roles)
        self.assertIn("explorer", roles)

        self.assertFalse(roles["act"].read_only)
        self.assertTrue(roles["explore"].read_only)
        self.assertTrue(roles["explorer"].read_only)
        self.assertEqual(roles["orchestrate"].scope, "main_only")

    def test_custom_role_parsing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            role_path = os.path.join(roles_dir, "reviewer.md")

            with open(role_path, "w", encoding="utf-8") as f:
                f.write("""---
name: Reviewer
description: Code reviewer role
read_only: true
tools: read, grep, glob
model: deepseek-chat
scope: subagent_only
---
You are a senior code reviewer role.""")

            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)

            self.assertIn("reviewer", roles)
            rev = roles["reviewer"]

            self.assertEqual(rev.name, "Reviewer")
            self.assertEqual(rev.description, "Code reviewer role")
            self.assertTrue(rev.read_only)
            self.assertEqual(rev.allowed_tools, ["read", "grep", "glob"])
            self.assertEqual(rev.tools, ["read", "grep", "glob"])  # Alias check
            self.assertEqual(rev.model, "deepseek-chat")
            self.assertEqual(rev.scope, "subagent_only")
            self.assertIn("senior code reviewer role", rev.prompt)
            self.assertEqual(rev.system_prompt, rev.prompt)  # Alias check

    def test_project_roles_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            sa_path = os.path.join(roles_dir, "tester.md")

            with open(sa_path, "w", encoding="utf-8") as f:
                f.write("""---
name: tester
description: Automated testing role
tools: shell
model: gpt-4o
---
You run tests and report coverage.""")

            reg = RoleRegistry()
            reg.reload(project_dir=tmpdir)
            defs = reg.list_definitions()

            self.assertIn("tester", defs)
            tester = reg.get_role("tester")
            self.assertEqual(tester.description, "Automated testing role")
            self.assertEqual(tester.allowed_tools, ["shell"])

    def test_is_tool_allowed_validation(self):
        role_ro = AgentRole(
            key="reviewer",
            name="Reviewer",
            read_only=True,
            allowed_tools=["read", "grep"]
        )

        # Read tool in allowed list -> ok
        self.assertIsNone(role_ro.is_tool_allowed("read"))
        # Shell not in allowed list -> blocked
        self.assertIsNotNone(role_ro.is_tool_allowed("shell"))
        # Edit is write tool & read_only -> blocked
        self.assertIsNotNone(role_ro.is_tool_allowed("edit"))

        # Test role_tool_error helper
        self.assertIsNotNone(role_tool_error(role_ro, "edit"))
        self.assertIsNone(role_tool_error(role_ro, "read"))

    def test_alias_resolution_in_is_tool_allowed(self):
        role_ro = AgentRole(
            key="reviewer",
            name="Reviewer",
            read_only=True,
            disallowed_tools=["invoke_subagent"]
        )

        # Alias 'subagent' resolves to 'invoke_subagent' via ALIAS_MAP -> blocked
        self.assertIsNotNone(role_ro.is_tool_allowed("subagent"))
        # Alias 'write_file' resolves to write tools -> blocked in read_only
        self.assertIsNotNone(role_ro.is_tool_allowed("write_file"))

    def test_scope_filtering(self):
        reg = RoleRegistry.get_instance()
        main_roles = reg.list_roles(scope="main_only")
        self.assertIn("orchestrate", main_roles)

        subagent_roles = reg.list_definitions()
        self.assertIn("worker", subagent_roles)
        self.assertIn("explorer", subagent_roles)
        self.assertNotIn("orchestrate", subagent_roles)


if __name__ == "__main__":
    unittest.main()
