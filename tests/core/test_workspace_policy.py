import os
import tempfile
import unittest
from pathlib import Path

from core.domain.policies.permission_policy import (
    LOGS_DIR,
    SECRETS_FILE,
    PermissionAction,
    evaluate_workspace_boundary,
    get_config_dir,
    is_path_within_workspace,
    is_secrets_file,
    is_secrets_shell_command,
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

    def test_tmp_directory_handling(self):
        tmp_target = "/tmp/test_workspace_check.txt"
        self.assertTrue(is_path_within_workspace(tmp_target, [], allow_temp=True))
        self.assertFalse(is_path_within_workspace(tmp_target, [], allow_temp=False))

        roots = [str(self.workspace)]
        self.assertTrue(is_path_within_workspace(tmp_target, roots, allow_temp=True))
        self.assertFalse(is_path_within_workspace(tmp_target, roots, allow_temp=False))

    def test_merge_perms_patterns_combines_and_preserves_deny(self):
        base = {
            "patterns": {
                "shell": [
                    {"pattern": "rm -rf *", "action": "deny"},
                    {"pattern": "git status*", "action": "ask"},
                ]
            }
        }
        override = {
            "patterns": {
                "shell": [
                    {"pattern": "rm -rf *", "action": "allow"},
                    {"pattern": "git status*", "action": "allow"},
                    {"pattern": "echo *", "action": "allow"},
                ]
            }
        }
        merge_perms(base, override)
        shell_patterns = {r["pattern"]: r["action"] for r in base["patterns"]["shell"]}
        self.assertEqual(shell_patterns["rm -rf *"], "deny")
        self.assertEqual(shell_patterns["git status*"], "allow")
        self.assertEqual(shell_patterns["echo *"], "allow")

    def test_logs_dir_read_allowed(self):
        roots = [str(self.workspace)]
        log_file = os.path.join(LOGS_DIR, "test_snapshot.log")

        # is_path_within_workspace with allowed_read_roots
        self.assertTrue(is_path_within_workspace(log_file, roots, allowed_read_roots=[LOGS_DIR]))
        # Without allowed_read_roots, it is not in workspace
        self.assertFalse(is_path_within_workspace(log_file, roots, allow_temp=True))

        # read tool: permitted (decision is None)
        dec_read = evaluate_workspace_boundary("read", {"path": log_file}, roots)
        self.assertIsNone(dec_read)

        # view_file tool: permitted (decision is None)
        dec_view = evaluate_workspace_boundary("view_file", {"path": log_file}, roots)
        self.assertIsNone(dec_view)

        # create and edit tools: require confirmation (ASK)
        dec_create = evaluate_workspace_boundary("create", {"path": log_file}, roots)
        self.assertIsNotNone(dec_create)
        self.assertEqual(dec_create.action, PermissionAction.ASK)
        self.assertIn("outside workspace roots", dec_create.reason)

        dec_edit = evaluate_workspace_boundary("edit", {"path": log_file}, roots)
        self.assertIsNotNone(dec_edit)
        self.assertEqual(dec_edit.action, PermissionAction.ASK)
        self.assertIn("outside workspace roots", dec_edit.reason)

    def test_secrets_file_blocked(self):
        roots = [str(self.workspace)]

        # Helper detection
        self.assertTrue(is_secrets_file(SECRETS_FILE))
        self.assertTrue(is_secrets_file("~/.johnston/secrets.json"))
        self.assertTrue(is_secrets_shell_command(f"cat {SECRETS_FILE}"))
        self.assertTrue(is_secrets_shell_command("cat ~/.johnston/secrets.json"))
        self.assertTrue(is_secrets_shell_command("echo test > ~/.johnston/secrets.json"))

        # Reading secrets.json is DENIED
        dec_read = evaluate_workspace_boundary("read", {"path": SECRETS_FILE}, roots)
        self.assertIsNotNone(dec_read)
        self.assertEqual(dec_read.action, PermissionAction.DENY)
        self.assertIn("secrets", dec_read.reason.lower())

        # Modifying secrets.json is DENIED
        dec_edit = evaluate_workspace_boundary("edit", {"path": SECRETS_FILE}, roots)
        self.assertIsNotNone(dec_edit)
        self.assertEqual(dec_edit.action, PermissionAction.DENY)

        dec_create = evaluate_workspace_boundary("create", {"path": SECRETS_FILE}, roots)
        self.assertIsNotNone(dec_create)
        self.assertEqual(dec_create.action, PermissionAction.DENY)

        # Shell command accessing secrets.json is DENIED
        dec_shell = evaluate_workspace_boundary("shell", {"command": f"cat {SECRETS_FILE}"}, roots)
        self.assertIsNotNone(dec_shell)
        self.assertEqual(dec_shell.action, PermissionAction.DENY)

        # Symlink inside workspace pointing to secrets.json is also DENIED
        link_to_secrets = self.workspace / "secrets_symlink.json"
        try:
            os.symlink(SECRETS_FILE, link_to_secrets)
            dec_symlink = evaluate_workspace_boundary("read", {"path": str(link_to_secrets)}, roots)
            self.assertIsNotNone(dec_symlink)
            self.assertEqual(dec_symlink.action, PermissionAction.DENY)
        finally:
            if link_to_secrets.is_symlink():
                link_to_secrets.unlink()

    def test_other_johnston_files_require_confirmation(self):
        roots = [str(self.workspace)]
        cfg_dir = get_config_dir()
        config_file = os.path.join(cfg_dir, "config.json")
        prompt_hist = os.path.join(cfg_dir, "prompt_history.json")

        # config.json requires ASK (outside workspace)
        dec_cfg = evaluate_workspace_boundary("read", {"path": config_file}, roots)
        self.assertIsNotNone(dec_cfg)
        self.assertEqual(dec_cfg.action, PermissionAction.ASK)
        self.assertIn("outside workspace roots", dec_cfg.reason)

        # prompt_history.json requires ASK (outside workspace)
        dec_hist = evaluate_workspace_boundary("read", {"path": prompt_hist}, roots)
        self.assertIsNotNone(dec_hist)
        self.assertEqual(dec_hist.action, PermissionAction.ASK)
        self.assertIn("outside workspace roots", dec_hist.reason)

