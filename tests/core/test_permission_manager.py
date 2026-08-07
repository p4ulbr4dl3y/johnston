import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.permission_manager import PermissionManager


class TestPermissionManager(unittest.TestCase):
    def setUp(self):
        self.pm = PermissionManager.get_instance()
        self.pm.clear_session_overrides()
        self.config_patcher = patch("core.permission_manager.CONFIG_FILE", "/nonexistent_test_config.json")
        self.config_patcher.start()

    def tearDown(self):
        self.config_patcher.stop()

    def test_default_permissions(self):
        # Read group -> allow by default
        action, _ = self.pm.check_permission("read")
        self.assertEqual(action, "allow")

        # Write group -> allow by default
        action, _ = self.pm.check_permission("create")
        self.assertEqual(action, "allow")

        # Exec group -> ask by default
        action, _ = self.pm.check_permission("shell", {"command": "ls"})
        self.assertEqual(action, "ask")

        # Net group -> ask by default
        action, _ = self.pm.check_permission("web_fetch")
        self.assertEqual(action, "ask")

    def test_shell_guard_overrides_allow(self):
        # Set session override for shell to allow
        self.pm.set_session_override("shell", "allow")

        # Unsafe command should still be flagged by shell_guard -> deny
        action, reason = self.pm.check_permission("shell", {"command": "rm -rf /"})
        self.assertEqual(action, "deny")
        self.assertIn("Shell Guard", reason)

    def test_session_override(self):
        action_before, _ = self.pm.check_permission("web_fetch")
        self.assertEqual(action_before, "ask")

        self.pm.set_session_override("web_fetch", "allow")
        action_after, _ = self.pm.check_permission("web_fetch")
        self.assertEqual(action_after, "allow")

    def test_project_permissions_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = os.path.join(tmpdir, ".johnston")
            os.makedirs(proj_dir, exist_ok=True)
            perm_file = os.path.join(proj_dir, "permissions.json")

            with open(perm_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "permissions": {
                            "groups": {"exec": "allow"},
                            "tools": {"web_fetch": "deny"},
                        }
                    },
                    f,
                )

            # exec group should now be allow for safe command
            action_exec, _ = self.pm.check_permission("shell", {"command": "echo hi"}, project_dir=tmpdir)
            self.assertEqual(action_exec, "allow")

            # web_fetch tool override should be deny
            action_net, _ = self.pm.check_permission("web_fetch", project_dir=tmpdir)
            self.assertEqual(action_net, "deny")

    def test_fail_closed_on_invalid_action_values(self):
        # Tool-level junk action must NOT silently allow.
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = os.path.join(tmpdir, ".johnston")
            os.makedirs(proj_dir, exist_ok=True)
            perm_file = os.path.join(proj_dir, "permissions.json")
            with open(perm_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"shell": "BOGUS"}}}, f)
            action, _ = self.pm.check_permission("shell", {"command": "echo hi"}, project_dir=tmpdir)
            self.assertEqual(action, "ask", "invalid action value must fail closed to 'ask', not 'allow'")

        # Whitespace around a valid action is tolerated (normalized), not silently treated as junk.
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = os.path.join(tmpdir, ".johnston")
            os.makedirs(proj_dir, exist_ok=True)
            perm_file = os.path.join(proj_dir, "permissions.json")
            with open(perm_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"web_fetch": " allow "}}}, f)
            action, _ = self.pm.check_permission("web_fetch", project_dir=tmpdir)
            self.assertEqual(action, "allow")

        # Group-level junk action
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = os.path.join(tmpdir, ".johnston")
            os.makedirs(proj_dir, exist_ok=True)
            perm_file = os.path.join(proj_dir, "permissions.json")
            with open(perm_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"groups": {"exec": "BOGUS"}}}, f)
            action, _ = self.pm.check_permission("shell", {"command": "echo hi"}, project_dir=tmpdir)
            self.assertEqual(action, "ask")

        # Default junk action (tool not covered by any group -> falls back to default)
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = os.path.join(tmpdir, ".johnston")
            os.makedirs(proj_dir, exist_ok=True)
            perm_file = os.path.join(proj_dir, "permissions.json")
            with open(perm_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"default": "WHATEVER"}}, f)
            action, _ = self.pm.check_permission("no_such_tool_xyz", project_dir=tmpdir)
            self.assertEqual(action, "ask")

    def test_session_override_invalid_action_ignored(self):
        self.pm.set_session_override("web_fetch", "bogus")
        action, _ = self.pm.check_permission("web_fetch")
        self.assertEqual(action, "ask", "invalid session override must be ignored")

        self.pm.set_session_override("web_fetch", " ALLOW ")
        action, _ = self.pm.check_permission("web_fetch")
        self.assertEqual(action, "allow", "valid action with whitespace must normalize")

    def test_update_permission_validation(self):
        with self.assertRaises(ValueError):
            self.pm.update_permission("tool", "web_fetch", "bogus")
        with self.assertRaises(ValueError):
            self.pm.update_permission("not_a_type", "web_fetch", "allow")
        with self.assertRaises(ValueError):
            self.pm.update_permission("shell_guard", "shell_guard", "maybe")

    def test_normalize_action(self):
        self.assertEqual(self.pm.normalize_action("  ALLOW "), "allow")
        self.assertEqual(self.pm.normalize_action("deny"), "deny")
        self.assertEqual(self.pm.normalize_action("junk"), "ask")
        self.assertEqual(self.pm.normalize_action("junk", default="deny"), "deny")
        self.assertEqual(self.pm.normalize_action(None), "ask")


if __name__ == "__main__":
    unittest.main()
