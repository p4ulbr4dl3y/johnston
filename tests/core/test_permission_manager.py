import json
import os
import tempfile
import unittest
from unittest.mock import patch

from johnston_core.domain.policies.permission_policy import (
    ExecutionMode,
    PermissionAction,
    get_config_dir,
    normalize_action,
)
from johnston_core.permission_manager import LOGS_DIR, SECRETS_FILE, PermissionManager


class TestPermissionManager(unittest.TestCase):
    def setUp(self):
        self.pm = PermissionManager.get_instance()
        self.pm.clear_session_overrides()
        self.config_patcher = patch("johnston_core.permission_manager.CONFIG_FILE", "/nonexistent_test_config.json")
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
        action = self.pm.check_permission("kill", {"id": "t1"}).action
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
        self.assertEqual(self.pm.check_permission("mcp_custom_tool").action, "ask")
        self.assertEqual(self.pm.check_permission("read").action, "allow")

        # 3. YOLO mode
        self.pm.set_session_mode("yolo")
        self.assertEqual(self.pm.check_permission("create").action, "allow")
        self.assertEqual(self.pm.check_permission("edit").action, "allow")
        self.assertEqual(self.pm.check_permission("shell").action, "allow")
        self.assertEqual(self.pm.check_permission("mcp_custom_tool").action, "allow")
        self.assertEqual(self.pm.check_permission("web_fetch").action, "allow")
        self.assertEqual(self.pm.check_permission("mcp_custom_tool").action, "allow")
        self.assertEqual(self.pm.check_permission("read").action, "allow")

    def test_mcp_tools_mode_baseline(self):
        # In review mode, MCP tools default to 'ask'
        self.pm.set_session_mode("review")
        decision = self.pm.check_permission("gh__search")
        self.assertEqual(decision.action, "ask")

        # In edits mode, MCP tools default to 'ask' (aligned with references/tools.md)
        self.pm.set_session_mode("edits")
        self.assertEqual(self.pm.check_permission("gh__search").action, "ask")

        # In yolo mode, MCP tools default to 'allow'
        self.pm.set_session_mode("yolo")
        self.assertEqual(self.pm.check_permission("gh__search").action, "allow")

        # An explicit config entry still wins over the MCP mode default
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"gh__search": "deny"}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
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

            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
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
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                action = self.pm.check_permission("shell", {"command": "echo hi"}).action
                self.assertEqual(action, "ask", "invalid action value must fail closed to 'ask', not 'allow'")

        # Whitespace around a valid action is tolerated (normalized), not silently treated as junk.
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"web_fetch": " allow "}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                action = self.pm.check_permission("web_fetch").action
                self.assertEqual(action, "allow")

        # Default junk action (builtin tool not covered by explicit setting -> falls back to default)
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"default": "WHATEVER"}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                action = self.pm.check_permission("read").action
                self.assertEqual(action, "ask")

        # MCP tool with junk default -> ask (fail-closed), not the allow default
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"default": "WHATEVER"}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
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
        """Repeated checks must not re-merge config from disk (result memoized)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"web_fetch": "deny"}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                first = self.pm.get_effective_permissions()
                second = self.pm.get_effective_permissions()
                # Merge result is memoized (same object), no re-merge per call.
                self.assertIs(first, second)

    def test_check_permission_reflects_config_change(self):
        """Editing config on disk (new mtime) must invalidate the permission cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"web_fetch": "deny"}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                self.assertEqual(self.pm.check_permission("web_fetch").action, "deny")
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump({"permissions": {"tools": {"web_fetch": "allow"}}}, f)
                # Windows filesystems may keep a coarse mtime; bump it so the
                # permission cache invalidation is deterministic.
                st = os.stat(cfg_file)
                os.utime(cfg_file, (st.st_atime, st.st_mtime + 2))
                self.assertEqual(self.pm.check_permission("web_fetch").action, "allow")

    def test_same_mtime_rewrite_invalidates_cache(self):
        """Regression: a config rewrite with identical (st_mtime_ns, st_size)
        must still be observed — otherwise a stale ALLOW persists after the admin
        locked the tool down to DENY."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"web_fetch": "allow"}}}, f)
            st = os.stat(cfg_file)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                self.assertEqual(self.pm.check_permission("web_fetch").action, "allow")
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump({"permissions": {"tools": {"web_fetch": "deny"}}}, f)
                # Restore exact mtime_ns and byte size so both cache keys match
                # what was seen before the rewrite.
                deny_size = os.path.getsize(cfg_file)
                with open(cfg_file, "ab") as f:
                    f.write(b" " * (st.st_size - deny_size))  # re-pad to original size (may be 0)
                os.utime(cfg_file, ns=(st.st_atime_ns, st.st_mtime_ns))
                self.assertEqual(
                    self.pm.check_permission("web_fetch").action,
                    "deny",
                    "same-mtime same-size rewrite must invalidate the permission cache",
                )

    def test_deleted_config_falls_back_to_defaults(self):
        """Removing the config file must drop the cached snapshot (no stale deny)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"web_fetch": "deny"}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
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
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
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

    def test_effective_cache_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"mode": "review"}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                self.pm.get_effective_permissions()
                self.assertIsNotNone(self.pm._effective_cache)
                self.assertEqual(len(self.pm._effective_cache), 4)
                paths, stamps, digests, perms = self.pm._effective_cache
                self.assertEqual(paths[0], cfg_file)
                self.assertIsInstance(stamps[0], tuple)
                self.assertEqual(len(stamps[0]), 2)
                self.assertIsInstance(digests[0], int)
                self.assertIsInstance(perms, dict)

    def test_logs_dir_read_allowed(self):
        log_file = os.path.join(LOGS_DIR, "snapshot_123.log")
        # Reading inside LOGS_DIR via read is allowed
        dec_read = self.pm.check_permission("read", {"path": log_file})
        self.assertEqual(dec_read.action, PermissionAction.ALLOW)

        # Reading inside LOGS_DIR via view_file is allowed
        dec_view = self.pm.check_permission("view_file", {"path": log_file})
        self.assertEqual(dec_view.action, PermissionAction.ALLOW)

        # Modifying LOGS_DIR via create / edit requires confirmation (ASK)
        dec_create = self.pm.check_permission("create", {"path": log_file})
        self.assertEqual(dec_create.action, PermissionAction.ASK)
        self.assertIn("outside workspace", dec_create.reason.lower())

        dec_edit = self.pm.check_permission("edit", {"path": log_file})
        self.assertEqual(dec_edit.action, PermissionAction.ASK)
        self.assertIn("outside workspace", dec_edit.reason.lower())

    def test_secrets_file_blocked_deny(self):
        # Reading secrets.json is blocked (DENY)
        dec_read = self.pm.check_permission("read", {"path": SECRETS_FILE})
        self.assertEqual(dec_read.action, PermissionAction.DENY)

        dec_view = self.pm.check_permission("view_file", {"path": SECRETS_FILE})
        self.assertEqual(dec_view.action, PermissionAction.DENY)

        # Modifying secrets.json is blocked (DENY)
        dec_edit = self.pm.check_permission("edit", {"path": SECRETS_FILE})
        self.assertEqual(dec_edit.action, PermissionAction.DENY)

        dec_create = self.pm.check_permission("create", {"path": SECRETS_FILE})
        self.assertEqual(dec_create.action, PermissionAction.DENY)

        # Shell command targeting secrets.json is blocked (DENY)
        dec_shell = self.pm.check_permission("shell", {"command": f"cat {SECRETS_FILE}"})
        self.assertEqual(dec_shell.action, PermissionAction.DENY)

        dec_shell_tilde = self.pm.check_permission("shell", {"command": "cat ~/.johnston/secrets.json"})
        self.assertEqual(dec_shell_tilde.action, PermissionAction.DENY)

    def test_secrets_file_blocked_cannot_be_bypassed_by_yolo_or_overrides(self):
        # Even in YOLO mode and with session override allow, secrets.json MUST be DENY
        self.pm.set_session_mode("yolo")
        self.pm.set_session_override("read", "allow")
        self.pm.set_session_override("shell", "allow")
        self.assertEqual(self.pm.check_permission("read", {"path": SECRETS_FILE}).action, PermissionAction.DENY)
        self.assertEqual(self.pm.check_permission("shell", {"command": f"cat {SECRETS_FILE}"}).action, PermissionAction.DENY)

    def test_other_johnston_files_require_confirmation(self):
        cfg_dir = get_config_dir()
        config_file = os.path.join(cfg_dir, "config.json")
        prompt_hist = os.path.join(cfg_dir, "prompt_history.json")

        dec_cfg = self.pm.check_permission("read", {"path": config_file})
        self.assertEqual(dec_cfg.action, PermissionAction.ASK)
        self.assertIn("outside workspace", dec_cfg.reason.lower())

        dec_hist = self.pm.check_permission("read", {"path": prompt_hist})
        self.assertEqual(dec_hist.action, PermissionAction.ASK)
        self.assertIn("outside workspace", dec_hist.reason.lower())

    def test_logs_dir_path_traversal(self):
        traversal_secrets = os.path.join(LOGS_DIR, "../secrets.json")
        traversal_config = os.path.join(LOGS_DIR, "../config.json")

        dec_sec = self.pm.check_permission("read", {"path": traversal_secrets})
        self.assertEqual(dec_sec.action, PermissionAction.DENY)

        dec_cfg = self.pm.check_permission("read", {"path": traversal_config})
        self.assertEqual(dec_cfg.action, PermissionAction.ASK)
        self.assertNotIn("Path outside workspace roots: Path", dec_cfg.reason)

    def test_shell_secrets_cd_and_globs(self):
        dec_cd = self.pm.check_permission("shell", {"command": "cd ~/.johnston && cat secrets.json"})
        self.assertEqual(dec_cd.action, PermissionAction.DENY)

        dec_glob = self.pm.check_permission("shell", {"command": "cat ~/.johnston/sec*"})
        self.assertEqual(dec_glob.action, PermissionAction.DENY)

    def test_search_tool_permissions(self):
        # search targeting secrets.json -> DENY
        dec_sec = self.pm.check_permission("search", {"path": "~/.johnston/secrets.json"})
        self.assertEqual(dec_sec.action, PermissionAction.DENY)

        # search outside workspace roots -> ASK (no duplicate reason prefix)
        dec_outside = self.pm.check_permission("search", {"path": "/etc/passwd"})
        self.assertEqual(dec_outside.action, PermissionAction.ASK)
        self.assertNotIn("Path outside workspace roots: Path", dec_outside.reason)
        self.assertIn("outside workspace roots", dec_outside.reason)

        # search targeting LOGS_DIR -> ALLOW
        dec_logs = self.pm.check_permission("search", {"path": LOGS_DIR})
        self.assertEqual(dec_logs.action, PermissionAction.ALLOW)

    def test_wildcard_tool_permissions(self):
        # 1. Session wildcard override (e.g. github__*)
        self.pm.set_session_mode("review")
        self.assertEqual(self.pm.check_permission("github__create_issue").action, "ask")

        self.pm.set_session_override("github__*", "allow")
        self.assertEqual(self.pm.check_permission("github__create_issue").action, "allow")
        self.assertEqual(self.pm.check_permission("github__list_repos").action, "allow")
        self.assertEqual(self.pm.check_permission("slack__post_message").action, "ask")

        # 2. Config wildcard deny wins over session allow
        self.pm.set_session_override("danger__run", "allow")
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"danger__*": "deny"}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                self.assertEqual(self.pm.check_permission("danger__run").action, "deny")

    def test_unsafe_shell_cannot_be_bypassed_by_session_override(self):
        self.pm.set_session_override("shell", "allow")
        # Normal command is allowed
        self.assertEqual(self.pm.check_permission("shell", {"command": "git status"}).action, PermissionAction.ALLOW)

        # Dynamic / unsafe commands must still require ASK
        dec = self.pm.check_permission("shell", {"command": "echo $(whoami)"})
        self.assertEqual(dec.action, PermissionAction.ASK)
        self.assertIn("dynamic/unsafe constructs", dec.reason)

        dec_eval = self.pm.check_permission("shell", {"command": "eval 'rm -rf /'"})
        self.assertEqual(dec_eval.action, PermissionAction.ASK)

        # In YOLO mode, execution is allowed without prompt
        self.pm.set_session_mode(ExecutionMode.YOLO)
        self.assertEqual(self.pm.check_permission("shell", {"command": "echo $(whoami)"}).action, PermissionAction.ALLOW)

    def test_wildcard_deny_priority_in_session_overrides(self):
        self.pm.set_session_override("github__*", "allow")
        self.pm.set_session_override("github__delete*", "deny")
        self.assertEqual(self.pm.check_permission("github__create_issue").action, PermissionAction.ALLOW)
        self.assertEqual(self.pm.check_permission("github__delete_repo").action, PermissionAction.DENY)

    def test_config_wildcard_deny_not_bypassed_by_session_wildcard_allow(self):
        """Regression: an admin config wildcard DENY (danger__* -> deny) must not
        be lifted by a session wildcard ALLOW (danger__* -> allow) or by a sibling
        wildcard like danger__run* -> allow. Only an exact session override of the
        same tool name may override a configured tool-level deny."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"danger__*": "deny"}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                self.pm.set_session_override("danger__*", "allow")
                dec = self.pm.check_permission("danger__delete")
                self.assertEqual(dec.action, PermissionAction.DENY, "wildcard session allow must not bypass config wildcard deny")

                self.pm.set_session_override("danger__*", "allow")  # exact key still not a grant
                dec2 = self.pm.check_permission("danger__delete")
                self.assertEqual(dec2.action, PermissionAction.DENY)

        # Exact same-tool session override still lifts the config deny (documented contract)
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"danger__run": "deny"}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                self.pm.set_session_override("danger__run", "allow")
                self.assertEqual(self.pm.check_permission("danger__run").action, PermissionAction.ALLOW)

    def test_config_wildcard_deny_is_absolute(self):
        """Regression: an admin config wildcard DENY (danger__* -> deny) is
        absolute — it cannot be lifted by a session wildcard allow NOR by an
        exact same-tool session override."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"danger__*": "deny"}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                self.pm.set_session_override("danger__run", "allow")
                dec = self.pm.check_permission("danger__run")
                self.assertEqual(dec.action, PermissionAction.DENY, "exact same-tool session override must not lift a config wildcard deny")

                dec2 = self.pm.check_permission("danger__delete")
                self.assertEqual(dec2.action, PermissionAction.DENY)

    def test_non_string_tool_config_fails_closed(self):
        """Regression: non-string tool permission values (null, numbers, lists,
        dicts) must fail closed to 'ask', never silently fall open to ALLOW."""
        for junk in (None, 12345, False, [], {}):
            with self.subTest(junk=junk):
                with tempfile.TemporaryDirectory() as tmpdir:
                    cfg_file = os.path.join(tmpdir, "config.json")
                    with open(cfg_file, "w", encoding="utf-8") as f:
                        json.dump({"permissions": {"tools": {"read": junk}}}, f)
                    with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                        dec = self.pm.check_permission("read", {"path": os.path.join(tmpdir, "x.py")})
                        self.assertEqual(
                            dec.action,
                            PermissionAction.ASK,
                            f"non-string tool config {junk!r} must fail closed to ask",
                        )
        # Explicit reason distinguishes invalid config from a real ask baseline
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"read": 999}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                dec = self.pm.check_permission("read", {"path": os.path.join(tmpdir, "x.py")})
                self.assertEqual(dec.action, PermissionAction.ASK)
                self.assertIn("Explicit tool permission", dec.reason)


class TestWorkspaceRootPersistence(unittest.TestCase):
    """Persistenced workspace-root scopes (session/local/project) via save_workspace_root."""

    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = os.path.realpath(self.temp_dir.name)
        os.chdir(self.project_dir)
        self.pm = PermissionManager.configure_instance()
        self.pm.set_project_dir(self.project_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.temp_dir.cleanup()
        self.pm.clear_session_overrides()

    def test_save_workspace_root_session(self):
        extra_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            used_scope = self.pm.save_workspace_root(extra_dir, scope="session")
            self.assertEqual(used_scope, "session")
            self.assertIn(extra_dir, self.pm.get_workspace_roots())

            # Verify nothing written to disk
            cfg_local = os.path.join(self.project_dir, ".johnston", "config.local.json")
            cfg_project = os.path.join(self.project_dir, ".johnston", "config.json")
            self.assertFalse(os.path.exists(cfg_local))
            self.assertFalse(os.path.exists(cfg_project))
        finally:
            os.rmdir(extra_dir)

    def test_save_workspace_root_project(self):
        extra_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            used_scope = self.pm.save_workspace_root(extra_dir, scope="project")
            self.assertEqual(used_scope, "project")
            self.assertIn(extra_dir, self.pm.get_workspace_roots())

            cfg_project = os.path.join(self.project_dir, ".johnston", "config.json")
            self.assertTrue(os.path.exists(cfg_project))
            with open(cfg_project, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn(extra_dir, data["permissions"]["writable_roots"])
        finally:
            os.rmdir(extra_dir)

    def test_save_workspace_root_auto_with_git(self):
        os.makedirs(os.path.join(self.project_dir, ".git"), exist_ok=True)
        extra_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            used_scope = self.pm.save_workspace_root(extra_dir)
            self.assertEqual(used_scope, "local")
            self.assertIn(extra_dir, self.pm.get_workspace_roots())

            cfg_local = os.path.join(self.project_dir, ".johnston", "config.local.json")
            self.assertTrue(os.path.exists(cfg_local))
            with open(cfg_local, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn(extra_dir, data["permissions"]["writable_roots"])

            # Verify .gitignore entry created
            gitignore = os.path.join(self.project_dir, ".gitignore")
            self.assertTrue(os.path.exists(gitignore))
            with open(gitignore, "r", encoding="utf-8") as f:
                self.assertIn(".johnston/config.local.json", f.read())
        finally:
            os.rmdir(extra_dir)

    def test_remove_persisted_workspace_root(self):
        extra_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            # First add to project config
            used_scope = self.pm.save_workspace_root(extra_dir, scope="project")
            self.assertEqual(used_scope, "project")
            self.assertIn(extra_dir, self.pm.get_workspace_roots())

            # Now remove
            self.pm.remove_persisted_workspace_root(extra_dir)
            self.assertNotIn(extra_dir, self.pm.get_workspace_roots())

            cfg_project = os.path.join(self.project_dir, ".johnston", "config.json")
            with open(cfg_project, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertNotIn(extra_dir, data["permissions"]["writable_roots"])
        finally:
            os.rmdir(extra_dir)


if __name__ == "__main__":
    unittest.main()


