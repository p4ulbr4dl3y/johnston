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
        self.assertEqual(roles["orchestrate"].name, "Orchestrate")
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
            self.assertEqual(rev.allowed_tools, ["read", "grep", "glob"])
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
            defs = reg.list_subagent_roles()

            self.assertIn("tester", defs)
            tester = reg.get_role("tester")
            self.assertEqual(tester.description, "Automated testing role")
            self.assertEqual(tester.allowed_tools, ["shell"])

    def test_is_tool_allowed_validation(self):
        role_ro = AgentRole(key="reviewer", name="Reviewer", read_only=True, allowed_tools=["read", "grep"])

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
        role_ro = AgentRole(key="reviewer", name="Reviewer", read_only=True, disallowed_tools=["invoke_subagent"])

        # Alias 'subagent' resolves to 'invoke_subagent' via ALIAS_MAP -> blocked
        self.assertIsNotNone(role_ro.is_tool_allowed("subagent"))
        # Alias 'write_file' resolves to write tools -> blocked in read_only
        self.assertIsNotNone(role_ro.is_tool_allowed("write_file"))

    def test_scope_filtering(self):
        reg = RoleRegistry.get_instance()
        main_roles = reg.list_roles(scope="main_only")
        self.assertIn("orchestrate", main_roles)

        subagent_roles = reg.list_subagent_roles()
        self.assertIn("worker", subagent_roles)
        self.assertIn("explorer", subagent_roles)
        self.assertNotIn("orchestrate", subagent_roles)

    def test_custom_md_role_with_list_disallowed_tools(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            md_path = os.path.join(roles_dir, "architect.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("""---
name: Architect
description: High-level design role
read_only: true
disallowed_tools: [create, edit]
---
Architect prompt content""")

            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            self.assertIn("architect", roles)
            arch = roles["architect"]
            self.assertEqual(arch.name, "Architect")
            self.assertTrue(arch.read_only)
            self.assertEqual(arch.prompt, "Architect prompt content")
            self.assertIn("create", arch.disallowed_tools)

    def test_role_tool_error_read_only_enforced(self):
        reg = RoleRegistry.get_instance()
        explore = reg.get_role("explore")

        # disallowed_tools still enforced
        self.assertIsNotNone(role_tool_error(explore, "create"))
        self.assertIsNotNone(role_tool_error(explore, "write_to_file"))
        # read_only blocks write tools even without explicit disallow
        self.assertIsNotNone(role_tool_error(explore, "edit"))
        self.assertIsNotNone(role_tool_error(explore, "multi_edit"))
        # read tools allowed in read-only mode
        self.assertIsNone(role_tool_error(explore, "read"))
        self.assertIsNone(role_tool_error(explore, "shell"))
        # act mode allows everything
        act = reg.get_role("act")
        self.assertIsNone(role_tool_error(act, "create"))

    def test_role_tool_error_custom_read_only_without_disallowed(self):
        ro_mode = AgentRole(key="ro", name="RO", read_only=True)
        self.assertIsNotNone(role_tool_error(ro_mode, "create"))
        self.assertIsNone(role_tool_error(ro_mode, "read"))


if __name__ == "__main__":
    unittest.main()
