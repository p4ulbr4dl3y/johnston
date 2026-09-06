import os
import tempfile
import unittest
from pathlib import Path

from core.domain.policies.permission_policy import (
    PermissionAction,
    evaluate_workspace_boundary,
    is_path_within_workspace,
    merge_perms,
)


class TestWorkspacePolicy(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp_dir.name) / "workspace"
        self.workspace.mkdir()
        self.outside_dir = Path(self.tmp_dir.name) / "outside"
        self.outside_dir.mkdir()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_path_inside_workspace(self):
        inside_file = self.workspace / "file.txt"
        inside_file.write_text("hello")
        self.assertTrue(is_path_within_workspace(str(inside_file), [str(self.workspace)]))
        self.assertTrue(is_path_within_workspace(str(self.workspace), [str(self.workspace)]))

        sub_file = self.workspace / "nested" / "dir" / "doc.md"
        self.assertTrue(is_path_within_workspace(str(sub_file), [str(self.workspace)]))

    def test_path_traversal(self):
        traversal = os.path.join(str(self.workspace), "../../etc/passwd")
        self.assertFalse(is_path_within_workspace(traversal, [str(self.workspace)], allow_temp=False))
        self.assertFalse(is_path_within_workspace("../../etc/passwd", [str(self.workspace)], allow_temp=False))

    def test_symlink_escape(self):
        # Symlink inside workspace pointing to outside directory
        secret_file = self.outside_dir / "secret.txt"
        secret_file.write_text("secret")
        symlink_file = self.workspace / "escape_link"
        os.symlink(secret_file, symlink_file)

        # allow_temp=False ensures temp parent directory does not mask the escape
        self.assertFalse(is_path_within_workspace(str(symlink_file), [str(self.workspace)], allow_temp=False))

        # Symlink pointing to /etc/hosts (outside temp as well)
        if os.path.exists("/etc/hosts"):
            hosts_link = self.workspace / "hosts_link"
            os.symlink("/etc/hosts", hosts_link)
            self.assertFalse(is_path_within_workspace(str(hosts_link), [str(self.workspace)], allow_temp=True))

        # Symlink pointing inside workspace should be True
        target_file = self.workspace / "real.txt"
        target_file.write_text("real")
        internal_link = self.workspace / "internal_link"
        os.symlink(target_file, internal_link)
        self.assertTrue(is_path_within_workspace(str(internal_link), [str(self.workspace)], allow_temp=False))

    def test_multiple_workspace_roots(self):
        root1 = self.workspace
        root2 = self.outside_dir
        roots = [str(root1), str(root2)]

        target1 = root1 / "a.txt"
        target2 = root2 / "b.txt"
        other = Path("/etc/passwd")

        self.assertTrue(is_path_within_workspace(str(target1), roots, allow_temp=False))
        self.assertTrue(is_path_within_workspace(str(target2), roots, allow_temp=False))
        self.assertFalse(is_path_within_workspace(str(other), roots, allow_temp=False))

    def test_system_temp_exceptions(self):
        temp_file = Path(tempfile.gettempdir()) / "test_temp_exception.txt"
        roots = [str(self.workspace)]

        self.assertTrue(is_path_within_workspace(str(temp_file), roots, allow_temp=True))
        self.assertFalse(is_path_within_workspace(str(temp_file), roots, allow_temp=False))

    def test_invalid_and_missing_paths(self):
        roots = [str(self.workspace)]
        self.assertFalse(is_path_within_workspace("", roots))
        self.assertFalse(is_path_within_workspace("   ", roots))
        self.assertFalse(is_path_within_workspace(None, roots))  # type: ignore[arg-type]
        self.assertFalse(is_path_within_workspace(str(self.workspace / "nonexistent.txt"), [], allow_temp=False))
        self.assertFalse(is_path_within_workspace("/some/nonexistent/path", [""], allow_temp=False))

    def test_evaluate_workspace_boundary_file_tools(self):
        roots = [str(self.workspace)]

        # Inside workspace -> None
        for tool in ("create", "edit", "read"):
            args = {"path": str(self.workspace / "test.py")}
            self.assertIsNone(evaluate_workspace_boundary(tool, args, roots))

        # Outside workspace -> ASK decision
        outside_path = "/etc/passwd"
        for tool in ("create", "edit", "read"):
            args = {"path": outside_path}
            decision = evaluate_workspace_boundary(tool, args, roots)
            self.assertIsNotNone(decision)
            self.assertEqual(decision.action, PermissionAction.ASK)
            self.assertEqual(decision.reason, f"Path '{outside_path}' is outside workspace roots")

    def test_evaluate_workspace_boundary_shell(self):
        roots = [str(self.workspace)]

        # Shell without cwd -> None
        self.assertIsNone(evaluate_workspace_boundary("shell", {"command": "ls"}, roots))

        # Shell with cwd inside workspace -> None
        self.assertIsNone(evaluate_workspace_boundary("shell", {"command": "ls", "cwd": str(self.workspace)}, roots))

        # Shell with cwd outside workspace -> ASK decision
        decision = evaluate_workspace_boundary("shell", {"command": "ls", "cwd": "/etc"}, roots)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.action, PermissionAction.ASK)
        self.assertEqual(decision.reason, "Path '/etc' is outside workspace roots")

    def test_evaluate_workspace_boundary_outside_action(self):
        roots = [str(self.workspace)]
        outside_path = "/etc/hosts"

        # Explicit DENY action enum
        decision = evaluate_workspace_boundary(
            "edit",
            {"path": outside_path},
            roots,
            outside_action=PermissionAction.DENY,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.action, PermissionAction.DENY)

        # String action "deny"
        decision_str = evaluate_workspace_boundary(
            "edit",
            {"path": outside_path},
            roots,
            outside_action="deny",  # type: ignore[arg-type]
        )
        self.assertIsNotNone(decision_str)
        self.assertEqual(decision_str.action, PermissionAction.DENY)

    def test_evaluate_workspace_boundary_irrelevant_tools(self):
        roots = [str(self.workspace)]
        self.assertIsNone(evaluate_workspace_boundary("web_fetch", {"url": "https://example.com"}, roots))
        self.assertIsNone(evaluate_workspace_boundary("ask_user", {"prompt": "hi"}, roots))
        self.assertIsNone(evaluate_workspace_boundary("shell", {"command": "echo 1", "cwd": ""}, roots))
        self.assertIsNone(evaluate_workspace_boundary("create", {"path": ""}, roots))
        self.assertIsNone(evaluate_workspace_boundary("create", None, roots))

    def test_merge_perms_writable_roots(self):
        base = {}
        merge_perms(base, {"writable_roots": ["/path/a", "/path/b"]})
        self.assertEqual(base["writable_roots"], ["/path/a", "/path/b"])

        # Merging with existing roots preserves order and prevents duplicates
        merge_perms(base, {"writable_roots": ["/path/b", "/path/c", "  "]})
        self.assertEqual(base["writable_roots"], ["/path/a", "/path/b", "/path/c"])

    def test_merge_perms_outside_workspace_action(self):
        base = {}
        merge_perms(base, {"outside_workspace_action": "deny"})
        self.assertEqual(base["outside_workspace_action"], "deny")

        merge_perms(base, {"outside_workspace_action": "ask"})
        self.assertEqual(base["outside_workspace_action"], "ask")

        merge_perms(base, {"outside_workspace_action": PermissionAction.DENY})
        self.assertEqual(base["outside_workspace_action"], "deny")

        # Invalid action should not override
        merge_perms(base, {"outside_workspace_action": "invalid_action"})
        self.assertEqual(base["outside_workspace_action"], "deny")
