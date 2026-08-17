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

        self.assertEqual(roles["explorer"].disallowed_tools, ["create", "edit", "multi_edit"])
        self.assertEqual(roles["orchestrator"].name, "Orchestrator")
        self.assertEqual(roles["orchestrator"].scope, "main")
        self.assertEqual(normalize_role_scope("main_only"), "main_only")
        self.assertEqual(normalize_role_scope("subagent_only"), "subagent_only")
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
allowed_tools: read, grep, glob
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
allowed_tools: shell
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
        role_ro = AgentRole(key="reviewer", name="Reviewer", disallowed_tools=["edit"], allowed_tools=["read", "grep"])

        # Read tool in allowed list -> ok
        self.assertIsNone(role_ro.is_tool_allowed("read"))
        # Shell not in allowed list -> blocked
        self.assertIsNotNone(role_ro.is_tool_allowed("shell"))
        # Edit in disallowed list -> blocked
        self.assertIsNotNone(role_ro.is_tool_allowed("edit"))

        # Test role_tool_error helper
        self.assertIsNotNone(role_tool_error(role_ro, "edit"))
        self.assertIsNone(role_tool_error(role_ro, "read"))

    def test_tool_name_normalizer_no_alias_resolution(self):
        from tools.registry import normalize_tool_name

        role_ro = AgentRole(
            key="reviewer",
            name="Reviewer",
            disallowed_tools=["invoke_subagent", "create"],
            tool_name_normalizer=normalize_tool_name,
        )

        # normalize_tool_name no longer resolves aliases: 'subagent' is not in the
        # disallowed list (which holds 'invoke_subagent'), so it is allowed.
        self.assertIsNone(role_ro.is_tool_allowed("subagent"))
        # Without a normalizer the result is the same (identity on lowercase).
        role_no_norm = AgentRole(key="reviewer", name="Reviewer", disallowed_tools=["invoke_subagent", "create"])
        self.assertIsNone(role_no_norm.is_tool_allowed("subagent"))
        # Canonical 'invoke_subagent' is blocked by the disallowed list.
        self.assertIsNotNone(role_ro.is_tool_allowed("invoke_subagent"))
        self.assertIsNone(role_ro.is_tool_allowed("write_file"))
        self.assertIsNotNone(role_ro.is_tool_allowed("create"))

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
disallowed_tools: [create, edit]
---
Architect prompt content""")

            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            self.assertIn("architect", roles)
            arch = roles["architect"]
            self.assertEqual(arch.name, "Architect")
            self.assertEqual(arch.prompt, "Architect prompt content")
            self.assertIn("create", arch.disallowed_tools)

    def test_role_tool_error_disallowed_enforced(self):
        reg = RoleRegistry.get_instance()
        explorer = reg.get_role("explorer")

        # disallowed_tools enforced
        self.assertIsNotNone(role_tool_error(explorer, "create"))
        self.assertIsNotNone(role_tool_error(explorer, "edit"))
        self.assertIsNotNone(role_tool_error(explorer, "multi_edit"))
        # read tools allowed
        self.assertIsNone(role_tool_error(explorer, "read"))
        self.assertIsNone(role_tool_error(explorer, "shell"))
        # worker mode allows everything
        worker = reg.get_role("worker")
        self.assertIsNone(role_tool_error(worker, "create"))

    def test_role_tool_error_allowed_tools_enforced(self):
        restricted = AgentRole(key="limited", name="Limited", allowed_tools=["read", "grep"])
        self.assertIsNone(role_tool_error(restricted, "read"))
        self.assertIsNotNone(role_tool_error(restricted, "shell"))
        self.assertIsNotNone(role_tool_error(restricted, "edit"))

        mode = type("Mode", (), {
            "name": "Limited",
            "allowed_tools": ["read", "grep"],
            "disallowed_tools": [],
        })()
        self.assertIsNone(role_tool_error(mode, "read"))
        self.assertIsNotNone(role_tool_error(mode, "shell"))


if __name__ == "__main__":
    unittest.main()
