import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.domain.policies.permission_policy import normalize_action
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
        # Builtin read defaults to 'allow' (default action is allow)
        action = self.pm.check_permission("read").action
        self.assertEqual(action, "allow")

        # Builtin create explicitly defaults to 'ask'
        action = self.pm.check_permission("create").action
        self.assertEqual(action, "ask")

        # Builtin edit/multi_edit explicitly default to 'ask'
        action = self.pm.check_permission("edit").action
        self.assertEqual(action, "ask")
        action = self.pm.check_permission("multi_edit").action
        self.assertEqual(action, "ask")

        # Builtin shell explicitly defaults to 'ask'
        action = self.pm.check_permission("shell", {"command": "ls"}).action
        self.assertEqual(action, "ask")

        # Other builtin tools fall back to the default 'allow'
        action = self.pm.check_permission("web_fetch").action
        self.assertEqual(action, "allow")
        action = self.pm.check_permission("ask_user").action
        self.assertEqual(action, "allow")

    def test_mcp_tools_default_allow(self):
        # MCP tools (not in the builtin registry) default to 'allow'
        decision = self.pm.check_permission("gh__search")
        self.assertEqual(decision.action, "allow")
        self.assertIn("MCP tool default", decision.reason)

        # An explicit config entry still wins over the MCP default
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"gh__search": "deny"}}}, f)
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                action = self.pm.check_permission("gh__search").action
                self.assertEqual(action, "deny")

    def test_session_override(self):
        action_before = self.pm.check_permission("web_fetch").action
        self.assertEqual(action_before, "allow")

        self.pm.set_session_override("web_fetch", "deny")
        action_after = self.pm.check_permission("web_fetch").action
        self.assertEqual(action_after, "deny")

    def test_global_tool_permissions_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "permissions": {
                            "default": "ask",
                            "tools": {"shell": "allow", "web_fetch": "deny"},
                        }
                    },
                    f,
                )

            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                # Explicit tool permission -> allow for safe command
                action_exec = self.pm.check_permission("shell", {"command": "echo hi"}).action
                self.assertEqual(action_exec, "allow")

                # Explicit tool permission -> deny
                action_net = self.pm.check_permission("web_fetch").action
                self.assertEqual(action_net, "deny")

    def test_fail_closed_on_invalid_action_values(self):
        # Tool-level junk action must NOT silently allow.
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"shell": "BOGUS"}}}, f)
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                action = self.pm.check_permission("shell", {"command": "echo hi"}).action
                self.assertEqual(action, "ask", "invalid action value must fail closed to 'ask', not 'allow'")

        # Whitespace around a valid action is tolerated (normalized), not silently treated as junk.
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"web_fetch": " allow "}}}, f)
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                action = self.pm.check_permission("web_fetch").action
                self.assertEqual(action, "allow")

        # Default junk action (builtin tool not covered by explicit setting -> falls back to default)
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"default": "WHATEVER"}}, f)
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                action = self.pm.check_permission("read").action
                self.assertEqual(action, "ask")

        # MCP tool with junk default -> ask (fail-closed), not the allow default
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"default": "WHATEVER"}}, f)
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                action = self.pm.check_permission("gh__search").action
                self.assertEqual(action, "ask")

    def test_session_override_invalid_action_ignored(self):
        self.pm.set_session_override("web_fetch", "bogus")
        action = self.pm.check_permission("web_fetch").action
        self.assertEqual(action, "ask", "invalid session override must be ignored")

        self.pm.set_session_override("web_fetch", " ALLOW ")
        action = self.pm.check_permission("web_fetch").action
        self.assertEqual(action, "allow", "valid action with whitespace must normalize")

    def test_update_permission_validation(self):
        with self.assertRaises(ValueError):
            self.pm.update_permission("tool", "web_fetch", "bogus")
        with self.assertRaises(ValueError):
            self.pm.update_permission("not_a_type", "web_fetch", "allow")
        with self.assertRaises(ValueError):
            self.pm.update_permission("group", "read", "allow")

    def test_update_permission_writes_global_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                self.pm.update_permission("tool", "web_fetch", "deny")

                # Tool permission persisted globally
                action = self.pm.check_permission("web_fetch").action
                self.assertEqual(action, "deny")

    def test_normalize_action(self):
        self.assertEqual(normalize_action("  ALLOW "), "allow")
        self.assertEqual(normalize_action("deny"), "deny")
        self.assertEqual(normalize_action("junk"), "ask")
        self.assertEqual(normalize_action("junk", default="deny"), "deny")
        self.assertEqual(normalize_action(None), "ask")

    def test_config_read_cached_across_checks(self):
        """Repeated checks must not re-read config from disk (mtime cache)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"web_fetch": "deny"}}}, f)
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                from core.models_catalog import _json_read_cache

                self.pm.check_permission("web_fetch")
                self.pm.check_permission("web_fetch")
                after = _json_read_cache.get(cfg_file)
                # Config file was read once and memoized despite two checks.
                self.assertIsNotNone(after)

    def test_check_permission_reflects_config_change(self):
        """Editing config on disk (new mtime) must invalidate the permission cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"web_fetch": "deny"}}}, f)
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                self.assertEqual(self.pm.check_permission("web_fetch").action, "deny")
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump({"permissions": {"tools": {"web_fetch": "allow"}}}, f)
                self.assertEqual(self.pm.check_permission("web_fetch").action, "allow")


if __name__ == "__main__":
    unittest.main()
