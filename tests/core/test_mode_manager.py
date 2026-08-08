import os
import tempfile
import unittest

from core.role_registry import AgentRole, RoleRegistry, role_tool_error


class TestRoleModeManager(unittest.TestCase):
    def test_builtin_modes(self):
        reg = RoleRegistry.get_instance()
        modes = reg.load_roles(include_global=False)
        self.assertIn("act", modes)
        self.assertIn("explore", modes)
        self.assertIn("orchestrate", modes)
        self.assertFalse(modes["act"].read_only)
        self.assertTrue(modes["explore"].read_only)
        self.assertFalse(modes["orchestrate"].read_only)
        self.assertEqual(modes["orchestrate"].name, "Orchestrate")

    def test_custom_md_role_with_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            md_path = os.path.join(roles_dir, "architect.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write('''---
name: Architect
description: High-level design role
read_only: true
disallowed_tools: [create, edit]
---
Architect prompt content''')

            reg = RoleRegistry()
            modes = reg.load_roles(project_dir=tmpdir, include_global=False)
            self.assertIn("architect", modes)
            arch = modes["architect"]
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
