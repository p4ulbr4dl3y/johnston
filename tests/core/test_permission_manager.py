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
        # Builtin read defaults to 'allow'
        action = self.pm.check_permission("read").action
        self.assertEqual(action, "allow")

        # Builtin create defaults to 'ask' in review mode
        action = self.pm.check_permission("create").action
        self.assertEqual(action, "ask")

        # Builtin edit defaults to 'ask' in review mode
        action = self.pm.check_permission("edit").action
        self.assertEqual(action, "ask")

        # Builtin shell defaults to 'ask' in review mode
        action = self.pm.check_permission("shell", {"command": "ls"}).action
        self.assertEqual(action, "ask")

        # In review mode, web_fetch is 'ask'
        action = self.pm.check_permission("web_fetch").action
        self.assertEqual(action, "ask")

        # ask_user and manage tools are 'allow'
        action = self.pm.check_permission("ask_user").action
        self.assertEqual(action, "allow")
        action = self.pm.check_permission("manage_shell", {"action": "list"}).action
        self.assertEqual(action, "allow")

    def test_execution_modes(self):
        # 1. Review mode
        self.pm.set_session_mode("review")
        self.assertEqual(self.pm.check_permission("create").action, "ask")
        self.assertEqual(self.pm.check_permission("edit").action, "ask")
        self.assertEqual(self.pm.check_permission("shell").action, "ask")
        self.assertEqual(self.pm.check_permission("web_fetch").action, "ask")
        self.assertEqual(self.pm.check_permission("mcp_custom_tool").action, "ask")
        self.assertEqual(self.pm.check_permission("read").action, "allow")

        # 2. Edits mode
        self.pm.set_session_mode("edits")
        self.assertEqual(self.pm.check_permission("create").action, "allow")
        self.assertEqual(self.pm.check_permission("edit").action, "allow")
        self.assertEqual(self.pm.check_permission("shell").action, "ask")
        self.assertEqual(self.pm.check_permission("web_fetch").action, "allow")
        self.assertEqual(self.pm.check_permission("mcp_custom_tool").action, "allow")
        self.assertEqual(self.pm.check_permission("read").action, "allow")

        # 3. YOLO mode
        self.pm.set_session_mode("yolo")
        self.assertEqual(self.pm.check_permission("create").action, "allow")
        self.assertEqual(self.pm.check_permission("edit").action, "allow")
        self.assertEqual(self.pm.check_permission("shell").action, "allow")
        self.assertEqual(self.pm.check_permission("web_fetch").action, "allow")
        self.assertEqual(self.pm.check_permission("mcp_custom_tool").action, "allow")
        self.assertEqual(self.pm.check_permission("read").action, "allow")

    def test_mcp_tools_mode_baseline(self):
        # In review mode, MCP tools default to 'ask'
        self.pm.set_session_mode("review")
        decision = self.pm.check_permission("gh__search")
        self.assertEqual(decision.action, "ask")

        # In edits and yolo, MCP tools default to 'allow'
        self.pm.set_session_mode("edits")
        self.assertEqual(self.pm.check_permission("gh__search").action, "allow")

        # An explicit config entry still wins over the MCP mode default
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"gh__search": "deny"}}}, f)
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                action = self.pm.check_permission("gh__search").action
                self.assertEqual(action, "deny")

    def test_session_override(self):
        action_before = self.pm.check_permission("web_fetch").action
        self.assertEqual(action_before, "ask")

        self.pm.set_session_override("web_fetch", "allow")
        action_after = self.pm.check_permission("web_fetch").action
        self.assertEqual(action_after, "allow")


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
        # Invalid action silently ignored per docstring; falls through to global default / mode baseline
        self.pm.set_session_override("web_fetch", "bogus")
        action = self.pm.check_permission("web_fetch").action
        self.assertEqual(action, "ask", "invalid session override must be ignored; falls through to mode baseline")

        # Valid action with whitespace normalizes correctly
        self.pm.set_session_override("web_fetch", " ALLOW ")
        action = self.pm.check_permission("web_fetch").action
        self.assertEqual(action, "allow")

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
                from core.infrastructure.platform.platform_utils import _json_read_cache

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
                # Windows filesystems may keep a coarse mtime; bump it so the
                # permission cache invalidation is deterministic.
                st = os.stat(cfg_file)
                os.utime(cfg_file, (st.st_atime, st.st_mtime + 2))
                self.assertEqual(self.pm.check_permission("web_fetch").action, "allow")

    def test_deleted_config_falls_back_to_defaults(self):
        """Removing the config file must drop the cached snapshot (no stale deny)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"web_fetch": "deny"}}}, f)
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                self.assertEqual(self.pm.check_permission("web_fetch").action, "deny")
                os.remove(cfg_file)
                # Missing file -> no cached snapshot -> review-mode baseline.
                self.assertEqual(self.pm.check_permission("web_fetch").action, "ask")

    def test_explicit_tool_config_case_insensitive(self):
        """Tool keys in config are matched case-insensitively (merge lowercases them)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"WEB_FETCH": "deny"}}}, f)
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                self.assertEqual(self.pm.check_permission("Web_Fetch").action, "deny")

    def test_configure_instance_replaces_singleton(self):
        """configure_instance wires a fresh singleton instead of poking _instance."""
        previous = PermissionManager.get_instance()
        try:
            configured = PermissionManager.configure_instance(tool_name_normalizer=str.upper)
            self.assertIs(PermissionManager.get_instance(), configured)
            self.assertEqual(configured.tool_name_normalizer, str.upper)
            self.assertEqual(configured._normalize_name("shell"), "SHELL")
        finally:
            PermissionManager._instance = previous


if __name__ == "__main__":
    unittest.main()
