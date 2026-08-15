import os
import tempfile
import unittest

from core.domain.policies.role_policy import AgentRole, normalize_role_scope, role_tool_error
from core.role_registry import (
    RoleRegistry,
)


class TestRoleRegistry(unittest.TestCase):
    def test_builtin_roles(self):
        reg = RoleRegistry.get_instance()
        roles = reg.load_roles(include_global=False)

        self.assertIn("worker", roles)
        self.assertIn("explorer", roles)
        self.assertIn("orchestrator", roles)

        self.assertFalse(roles["worker"].read_only)
        self.assertTrue(roles["explorer"].read_only)
        self.assertEqual(roles["orchestrator"].name, "Orchestrator")
        self.assertEqual(roles["orchestrator"].scope, "main")
        self.assertEqual(normalize_role_scope("main_only"), "main")
        self.assertEqual(normalize_role_scope("subagent_only"), "subagent")
        self.assertEqual(normalize_role_scope("any"), "any")

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
provider: clinepass
scope: subagent
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
            self.assertEqual(rev.provider, "clinepass")
            self.assertEqual(rev.scope, "subagent")
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
            reg.load_roles(project_dir=tmpdir)
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
        from tools.registry import normalize_tool_name

        role_ro = AgentRole(
            key="reviewer",
            name="Reviewer",
            read_only=True,
            disallowed_tools=["invoke_subagent"],
            tool_name_normalizer=normalize_tool_name,
        )

        # Alias 'subagent' resolves to 'invoke_subagent' via ALIAS_MAP -> blocked
        self.assertIsNotNone(role_ro.is_tool_allowed("subagent"))
        # Without a normalizer, aliases are not resolved and 'subagent' is allowed
        role_no_norm = AgentRole(key="reviewer", name="Reviewer", read_only=True, disallowed_tools=["invoke_subagent"])
        self.assertIsNone(role_no_norm.is_tool_allowed("subagent"))
        # Alias 'write_file' resolves to write tools -> blocked in read_only
        self.assertIsNotNone(role_ro.is_tool_allowed("write_file"))

    def test_scope_filtering(self):
        reg = RoleRegistry.get_instance()
        main_roles = reg.list_roles(scope="main")
        self.assertIn("orchestrator", main_roles)

        subagent_roles = reg.list_subagent_roles()
        self.assertIn("worker", subagent_roles)
        self.assertIn("explorer", subagent_roles)
        self.assertNotIn("orchestrator", subagent_roles)

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
        explorer = reg.get_role("explorer")

        # disallowed_tools still enforced
        self.assertIsNotNone(role_tool_error(explorer, "create"))
        self.assertIsNotNone(role_tool_error(explorer, "write_to_file"))
        # read_only blocks write tools even without explicit disallow
        self.assertIsNotNone(role_tool_error(explorer, "edit"))
        self.assertIsNotNone(role_tool_error(explorer, "multi_edit"))
        # read tools allowed in read-only mode
        self.assertIsNone(role_tool_error(explorer, "read"))
        self.assertIsNone(role_tool_error(explorer, "shell"))
        # worker mode allows everything
        worker = reg.get_role("worker")
        self.assertIsNone(role_tool_error(worker, "create"))

    def test_role_tool_error_allowed_tools_enforced(self):
        # Regression: role_tool_error must honor allowed_tools (previous buggy
        # free function ignored the allow-list and let restricted tools through).
        restricted = AgentRole(key="limited", name="Limited", allowed_tools=["read", "grep"])
        self.assertIsNone(role_tool_error(restricted, "read"))
        self.assertIsNotNone(role_tool_error(restricted, "shell"))
        self.assertIsNotNone(role_tool_error(restricted, "edit"))

        # Parrot an AgentRole through the non-AgentRole duck-typed mode branch too.
        mode = type("Mode", (), {
            "name": "Limited",
            "allowed_tools": ["read", "grep"],
            "disallowed_tools": [],
            "read_only": False,
        })()
        self.assertIsNone(role_tool_error(mode, "read"))
        self.assertIsNotNone(role_tool_error(mode, "shell"))

    def test_role_tool_error_custom_read_only_without_disallowed(self):
        ro_mode = AgentRole(key="ro", name="RO", read_only=True)
        self.assertIsNotNone(role_tool_error(ro_mode, "create"))
        self.assertIsNone(role_tool_error(ro_mode, "read"))


if __name__ == "__main__":
    unittest.main()
