import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.application.permission.permission_manager import PermissionManager
from core.domain.policies.permission_policy import ExecutionMode, PermissionAction


class TestPermissionCascadeMultitier(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp_dir.name)

        self.global_config_file = str(self.base_dir / "global_config.json")
        self.project_dir = str(self.base_dir / "project")
        os.makedirs(self.project_dir, exist_ok=True)
        # Create a .git directory inside project_dir to simulate a git repository
        os.makedirs(os.path.join(self.project_dir, ".git"), exist_ok=True)

        # Use a path outside temp directories (/tmp, /private/tmp, gettempdir)
        self.outside_dir = "/opt/outside"
        self.outside_file = os.path.join(self.outside_dir, "outside.py")

        self.patcher = patch("core.application.permission.permission_manager.CONFIG_FILE", self.global_config_file)
        self.patcher.start()

        self.pm = PermissionManager()
        self.pm.set_project_dir(self.project_dir)

    def tearDown(self):
        self.patcher.stop()
        self.tmp_dir.cleanup()

    def _write_json(self, path: str, data: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_3tier_cascade_project_wins_over_global(self):
        """Global sets 'edit': 'ask', Project sets 'edit': 'allow' -> Project wins."""
        # 1. Global config: 'edit' -> 'ask'
        self._write_json(self.global_config_file, {"permissions": {"tools": {"edit": "ask"}}})

        # 2. Project config: 'edit' -> 'allow'
        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        self._write_json(project_config, {"permissions": {"tools": {"edit": "allow"}}})

        effective = self.pm.get_effective_permissions(self.project_dir)
        self.assertEqual(effective["tools"]["edit"], "allow")

        decision = self.pm.check_permission("edit", {"path": os.path.join(self.project_dir, "file.py")})
        self.assertEqual(decision.action, PermissionAction.ALLOW)

    def test_local_config_overrides_project_config(self):
        """Local config.local.json overrides Project config.json."""
        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        self._write_json(project_config, {"permissions": {"tools": {"edit": "allow"}}})

        local_config = os.path.join(self.project_dir, ".johnston", "config.local.json")
        self._write_json(local_config, {"permissions": {"tools": {"edit": "deny"}}})

        effective = self.pm.get_effective_permissions(self.project_dir)
        self.assertEqual(effective["tools"]["edit"], "deny")

        decision = self.pm.check_permission("edit", {"path": os.path.join(self.project_dir, "file.py")})
        self.assertEqual(decision.action, PermissionAction.DENY)

    def test_session_override_overrides_local_project_global(self):
        """Session override overrides local, project, and global config."""
        self._write_json(self.global_config_file, {"permissions": {"tools": {"edit": "ask"}}})
        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        self._write_json(project_config, {"permissions": {"tools": {"edit": "ask"}}})
        local_config = os.path.join(self.project_dir, ".johnston", "config.local.json")
        self._write_json(local_config, {"permissions": {"tools": {"edit": "deny"}}})

        # Session override takes precedence
        self.pm.set_session_override("edit", "allow")
        decision = self.pm.check_permission("edit", {"path": os.path.join(self.project_dir, "file.py")})
        self.assertEqual(decision.action, PermissionAction.ALLOW)
        self.assertIn("Session override", decision.reason)

    def test_workspace_boundary_edits_mode_inside_workspace(self):
        """In edits mode: edit file inside workspace -> ALLOW."""
        self.pm.set_session_mode("edits")
        inside_file = os.path.join(self.project_dir, "inside.py")
        decision = self.pm.check_permission("edit", {"path": inside_file})
        self.assertEqual(decision.action, PermissionAction.ALLOW)

    def test_workspace_boundary_edits_mode_outside_workspace(self):
        """In edits mode: edit file outside workspace -> ASK (reason mentions outside workspace)."""
        self.pm.set_session_mode("edits")
        outside_file = os.path.join(self.outside_dir, "outside.py")
        decision = self.pm.check_permission("edit", {"path": outside_file})
        self.assertEqual(decision.action, PermissionAction.ASK)
        self.assertIn("outside workspace", decision.reason.lower())

    def test_workspace_boundary_outside_workspace_action_deny(self):
        """If outside_workspace_action is 'deny': edit file outside workspace -> DENY."""
        self.pm.set_session_mode("edits")
        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        self._write_json(project_config, {"permissions": {"outside_workspace_action": "deny"}})

        outside_file = os.path.join(self.outside_dir, "outside.py")
        decision = self.pm.check_permission("edit", {"path": outside_file})
        self.assertEqual(decision.action, PermissionAction.DENY)
        self.assertIn("outside workspace", decision.reason.lower())

    def test_workspace_boundary_add_workspace_root(self):
        """When add_workspace_root(outside_dir) is called: edit file in outside_dir -> now ALLOW."""
        self.pm.set_session_mode("edits")
        outside_file = os.path.join(self.outside_dir, "outside.py")

        # Initially outside -> ASK
        decision = self.pm.check_permission("edit", {"path": outside_file})
        self.assertEqual(decision.action, PermissionAction.ASK)

        # Add root -> now ALLOW
        self.pm.add_workspace_root(self.outside_dir)
        decision = self.pm.check_permission("edit", {"path": outside_file})
        self.assertEqual(decision.action, PermissionAction.ALLOW)

        # Remove root -> back to ASK
        self.pm.remove_workspace_root(self.outside_dir)
        decision = self.pm.check_permission("edit", {"path": outside_file})
        self.assertEqual(decision.action, PermissionAction.ASK)

    def test_workspace_boundary_tmp_files_allowed(self):
        """/tmp files are allowed by default temp exception."""
        self.pm.set_session_mode("edits")
        temp_file = os.path.join(tempfile.gettempdir(), "test_boundary_temp.py")
        decision = self.pm.check_permission("edit", {"path": temp_file})
        self.assertEqual(decision.action, PermissionAction.ALLOW)

    def test_workspace_boundary_review_mode(self):
        """In review mode: modifying tools baseline is ASK; if outside_workspace_action is DENY, apply DENY."""
        self.pm.set_session_mode("review")
        inside_file = os.path.join(self.project_dir, "inside.py")
        outside_file = os.path.join(self.outside_dir, "outside.py")

        # Modifying tools default to ASK in review mode
        decision = self.pm.check_permission("edit", {"path": inside_file})
        self.assertEqual(decision.action, PermissionAction.ASK)

        decision = self.pm.check_permission("edit", {"path": outside_file})
        self.assertEqual(decision.action, PermissionAction.ASK)

        # When outside_workspace_action is deny, outside becomes DENY
        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        self._write_json(project_config, {"permissions": {"outside_workspace_action": "deny"}})

        decision = self.pm.check_permission("edit", {"path": outside_file})
        self.assertEqual(decision.action, PermissionAction.DENY)

    def test_workspace_boundary_review_mode_read_outside(self):
        """In review mode: read inside workspace is ALLOW; read outside workspace returns ASK (or DENY)."""
        self.pm.set_session_mode("review")
        inside_file = os.path.join(self.project_dir, "inside.py")
        outside_file = os.path.join(self.outside_dir, "outside.py")

        # Read inside workspace is ALLOW in review mode
        decision = self.pm.check_permission("read", {"path": inside_file})
        self.assertEqual(decision.action, PermissionAction.ALLOW)

        # Read outside workspace defaults to ASK (not ALLOW baseline)
        decision = self.pm.check_permission("read", {"path": outside_file})
        self.assertEqual(decision.action, PermissionAction.ASK)
        self.assertIn("outside workspace", decision.reason.lower())

        # When outside_workspace_action is deny, read outside becomes DENY
        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        self._write_json(project_config, {"permissions": {"outside_workspace_action": "deny"}})
        decision = self.pm.check_permission("read", {"path": outside_file})
        self.assertEqual(decision.action, PermissionAction.DENY)

    def test_session_override_cannot_bypass_workspace_boundary(self):
        """Session overrides and tool config allowances cannot bypass workspace boundary."""
        self.pm.set_session_override("edit", "allow")
        self.pm.set_session_override("read", "allow")

        inside_file = os.path.join(self.project_dir, "inside.py")
        outside_file = os.path.join(self.outside_dir, "outside.py")

        # Inside file respects session override allow
        dec_inside = self.pm.check_permission("edit", {"path": inside_file})
        self.assertEqual(dec_inside.action, PermissionAction.ALLOW)

        # Outside file is stopped by workspace boundary despite session override
        dec_outside_edit = self.pm.check_permission("edit", {"path": outside_file})
        self.assertEqual(dec_outside_edit.action, PermissionAction.ASK)
        self.assertIn("outside workspace", dec_outside_edit.reason.lower())

        dec_outside_read = self.pm.check_permission("read", {"path": outside_file})
        self.assertEqual(dec_outside_read.action, PermissionAction.ASK)
        self.assertIn("outside workspace", dec_outside_read.reason.lower())

    def test_auto_gitignore_adds_local_config(self):
        """Auto-gitignore adds .johnston/config.local.json to .gitignore."""
        local_config = os.path.join(self.project_dir, ".johnston", "config.local.json")
        self._write_json(local_config, {"permissions": {"tools": {"shell": "allow"}}})

        gitignore_path = os.path.join(self.project_dir, ".gitignore")
        self.assertFalse(os.path.exists(gitignore_path))

        # Accessing effective permissions triggers auto-gitignore
        self.pm.get_effective_permissions(self.project_dir)

        self.assertTrue(os.path.exists(gitignore_path))
        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(".johnston/config.local.json", content)

        # Repeated calls do not duplicate entry
        self.pm.get_effective_permissions(self.project_dir)
        with open(gitignore_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip() == ".johnston/config.local.json"]
        self.assertEqual(len(lines), 1)

    def test_auto_gitignore_appends_to_existing_gitignore(self):
        """Auto-gitignore appends to existing .gitignore file without losing previous entries."""
        gitignore_path = os.path.join(self.project_dir, ".gitignore")
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("node_modules/\n*.pyc\n")

        local_config = os.path.join(self.project_dir, ".johnston", "config.local.json")
        self._write_json(local_config, {"permissions": {"tools": {"shell": "allow"}}})

        self.pm.get_effective_permissions(self.project_dir)

        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("node_modules/", content)
        self.assertIn("*.pyc", content)
        self.assertIn(".johnston/config.local.json", content)

    def test_auto_gitignore_no_git_does_nothing(self):
        """If project is not a git repo, auto-gitignore does not create .gitignore."""
        non_git_dir = str(self.base_dir / "non_git_project")
        os.makedirs(non_git_dir, exist_ok=True)
        local_config = os.path.join(non_git_dir, ".johnston", "config.local.json")
        self._write_json(local_config, {"permissions": {"tools": {"shell": "allow"}}})

        # Mock is_git_repository to return False
        with patch("core.application.permission.permission_manager.is_git_repository", return_value=False):
            self.pm.get_effective_permissions(non_git_dir)
            gitignore_path = os.path.join(non_git_dir, ".gitignore")
            self.assertFalse(os.path.exists(gitignore_path))

    def test_get_workspace_roots_combines_configured_roots(self):
        """get_workspace_roots combines workspace_roots with writable_roots from config."""
        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        extra_path = str(self.base_dir / "extra_writable")
        os.makedirs(extra_path, exist_ok=True)
        self._write_json(project_config, {"permissions": {"writable_roots": [extra_path]}})

        roots = self.pm.get_workspace_roots(self.project_dir)
        self.assertIn(os.path.realpath(self.project_dir), roots)
        self.assertIn(os.path.realpath(extra_path), roots)

    def test_set_project_dir_updates_primary_root(self):
        """set_project_dir updates current_project_dir and places primary root at index 0."""
        new_proj = str(self.base_dir / "another_proj")
        os.makedirs(new_proj, exist_ok=True)
        self.pm.add_workspace_root(self.outside_dir)

        self.pm.set_project_dir(new_proj)
        self.assertEqual(self.pm.current_project_dir, os.path.realpath(new_proj))
        self.assertEqual(self.pm.workspace_roots[0], os.path.realpath(new_proj))
        self.assertIn(os.path.realpath(self.outside_dir), self.pm.workspace_roots)

    def test_mode_cascade_project_overrides_global(self):
        """Project config mode overrides global mode."""
        self._write_json(self.global_config_file, {"permissions": {"mode": "review"}})
        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        self._write_json(project_config, {"permissions": {"mode": "edits"}})

        self.pm.set_project_dir(self.project_dir)
        self.assertEqual(self.pm.execution_mode, ExecutionMode.EDITS)

    def test_get_workspace_roots_resolves_relative_path(self):
        """get_workspace_roots resolves relative writable_roots against project_dir."""
        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        sibling_path = str(self.base_dir / "sibling_dir")
        os.makedirs(sibling_path, exist_ok=True)
        # Relative path from project_dir to sibling_dir is "../sibling_dir"
        self._write_json(project_config, {"permissions": {"writable_roots": ["../sibling_dir"]}})

        roots = self.pm.get_workspace_roots(self.project_dir)
        self.assertIn(os.path.realpath(sibling_path), roots)

    def test_writable_roots_ancestor_entries_ignored(self):
        """Regression: writable_roots resolving to a strict ancestor of the
        project (bare '..' or '/' or a '..' chain) must not widen the workspace."""
        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        self._write_json(
            project_config,
            {"permissions": {"writable_roots": ["..", os.path.dirname(self.project_dir), "/"]}},
        )

        roots = self.pm.get_workspace_roots(self.project_dir)
        self.assertNotIn(os.path.realpath(os.path.dirname(self.project_dir)), roots)
        self.assertNotIn(os.path.abspath("/"), roots)
        self.assertIn(os.path.realpath(self.project_dir), roots)  # primary root kept

    def test_same_mtime_same_size_rewrite_cascade(self):
        """Regression: effective-permissions cache keyed only by (mtime, size)
        would keep a stale ALLOW after an equal-size same-mtime config rewrite
        to DENY."""
        from core.infrastructure.platform.platform_utils import invalidate_json_read_cache

        project_config = os.path.join(self.project_dir, ".johnston", "config.json")
        self._write_json(project_config, {"permissions": {"tools": {"edit": "allow"}}})

        self.assertEqual(self.pm.check_permission("edit", {"path": os.path.join(self.project_dir, "f.py")}).action, "allow")

        # Rewrite to deny with identical byte size and restored original mtime_ns.
        deny_text = json.dumps({"permissions": {"tools": {"edit": "deny"}}}, indent=2)
        allow_text = json.dumps({"permissions": {"tools": {"edit": "allow"}}}, indent=2)
        deny_padded = deny_text + " " * (len(allow_text) - len(deny_text))
        self.assertEqual(len(deny_padded), len(allow_text))
        st = os.stat(project_config)
        with open(project_config, "w", encoding="utf-8") as f:
            f.write(deny_padded)
        os.utime(project_config, ns=(st.st_atime_ns, st.st_mtime_ns))
        invalidate_json_read_cache(project_config)  # bypass only the shared json read cache

        dec = self.pm.check_permission("edit", {"path": os.path.join(self.project_dir, "f.py")})
        self.assertEqual(dec.action, PermissionAction.DENY, "same-mtime same-size rewrite must invalidate the cascade cache")


if __name__ == "__main__":
    unittest.main()
