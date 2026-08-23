import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.domain.policies.permission_policy import (
    PermissionAction,
    evaluate_pattern_rules,
    extract_command_signature,
    extract_shell_subcommands,
    has_unsafe_shell_syntax,
    match_path_pattern,
    match_pattern,
    suggest_pattern,
)
from core.permission_manager import PermissionManager


class TestPatternPolicyHelpers(unittest.TestCase):
    def test_extract_shell_subcommands(self):
        self.assertEqual(extract_shell_subcommands("ls -la"), ["ls -la"])
        self.assertEqual(
            extract_shell_subcommands("git status && pytest -v ; echo done || cat log.txt | grep error"),
            ["git status", "pytest -v", "echo done", "cat log.txt", "grep error"],
        )
        self.assertEqual(extract_shell_subcommands("cargo test 2>&1"), ["cargo test 2>&1"])
        self.assertEqual(extract_shell_subcommands(""), [])
        self.assertEqual(extract_shell_subcommands(None), [])

    def test_has_unsafe_shell_syntax(self):
        self.assertTrue(has_unsafe_shell_syntax("echo $(whoami)"))
        self.assertTrue(has_unsafe_shell_syntax("cat `pwd`/file"))
        self.assertTrue(has_unsafe_shell_syntax("bash -c 'rm -rf /'"))
        self.assertTrue(has_unsafe_shell_syntax("powershell -c 'dir'"))
        self.assertTrue(has_unsafe_shell_syntax("pwsh -c 'Get-Process'"))
        self.assertTrue(has_unsafe_shell_syntax("sh -c 'echo 1'"))
        self.assertTrue(has_unsafe_shell_syntax("eval 'dangerous'"))
        self.assertTrue(has_unsafe_shell_syntax("exec /bin/sh"))
        self.assertFalse(has_unsafe_shell_syntax("git status"))
        self.assertFalse(has_unsafe_shell_syntax("cat foo.txt && pytest -k test_foo"))

    def test_extract_command_signature(self):
        self.assertEqual(extract_command_signature("cat file.txt"), "cat *")
        self.assertEqual(extract_command_signature("/usr/bin/cat file.txt"), "cat *")
        self.assertEqual(extract_command_signature("git status"), "git status *")
        self.assertEqual(extract_command_signature("git commit -m 'test'"), "git commit *")
        self.assertEqual(extract_command_signature("sudo env FOO=1 git diff"), "git diff *")
        self.assertEqual(extract_command_signature("pytest -v tests/"), "pytest *")
        self.assertEqual(extract_command_signature("docker run -it ubuntu"), "docker run *")
        self.assertEqual(extract_command_signature(""), "")

    def test_match_pattern(self):
        self.assertTrue(match_pattern("git status", "git status*"))
        self.assertTrue(match_pattern("pytest -v", "pytest *"))
        self.assertFalse(match_pattern("rm -rf /", "git *"))
        self.assertFalse(match_pattern("val", ""))

    def test_match_path_pattern(self):
        self.assertTrue(match_path_pattern("tests/unit/test_a.py", "tests/**"))
        self.assertTrue(match_path_pattern("/app/tests/unit/test_a.py", "tests/**"))
        self.assertTrue(match_path_pattern(".env", ".env*"))
        self.assertTrue(match_path_pattern("/home/user/.env.production", ".env*"))
        self.assertTrue(match_path_pattern("src/main.py", "src/*.py"))
        self.assertFalse(match_path_pattern("src/main.py", "tests/**"))
        self.assertFalse(match_path_pattern("tests/../../etc/shadow", "tests/**"))


    def test_suggest_pattern(self):
        self.assertEqual(suggest_pattern("shell", {"command": "git checkout -b fix"}), "git checkout *")
        self.assertEqual(suggest_pattern("shell", {"command": "cat a.txt"}), "cat *")
        self.assertEqual(suggest_pattern("edit", {"path": "tests/ui/test_modal.py"}), "tests/ui/**")
        self.assertEqual(suggest_pattern("read", {"path": "README.md"}), "README.md")
        self.assertEqual(
            suggest_pattern("web_fetch", {"url": "https://docs.python.org/3/library/os.html"}),
            "https://docs.python.org/*",
        )
        self.assertIsNone(suggest_pattern("ask_user", {}))

    def test_evaluate_pattern_rules_shell(self):
        rules = [
            {"pattern": "git status*", "action": "allow"},
            {"pattern": "cat *", "action": "allow"},
            {"pattern": "rm -rf *", "action": "deny"},
            {"pattern": "pytest *", "action": "ask"},
        ]

        # Allowed single command
        dec = evaluate_pattern_rules("shell", {"command": "git status"}, rules)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.action, PermissionAction.ALLOW)

        # Denied command
        dec = evaluate_pattern_rules("shell", {"command": "rm -rf /tmp/test"}, rules)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.action, PermissionAction.DENY)

        # Compound: both allowed -> allow
        dec = evaluate_pattern_rules("shell", {"command": "cat file.txt && git status"}, rules)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.action, PermissionAction.ALLOW)

        # Compound: one deny -> deny
        dec = evaluate_pattern_rules("shell", {"command": "cat file.txt && rm -rf foo"}, rules)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.action, PermissionAction.DENY)

        # Compound: one ask -> ask
        dec = evaluate_pattern_rules("shell", {"command": "cat file.txt && pytest -v"}, rules)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.action, PermissionAction.ASK)

        # Unmatched command -> None (fallback)
        dec = evaluate_pattern_rules("shell", {"command": "curl https://example.com"}, rules)
        self.assertIsNone(dec)

        # Unsafe shell -> ask
        dec = evaluate_pattern_rules("shell", {"command": "cat $(pwd)/foo"}, rules)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.action, PermissionAction.ASK)


class TestPermissionManagerPatterns(unittest.TestCase):
    def setUp(self):
        self.pm = PermissionManager()
        self.pm.clear_session_overrides()

    def test_session_pattern_override(self):
        # Default shell is ask
        dec_before = self.pm.check_permission("shell", {"command": "cat a.txt"})
        self.assertEqual(dec_before.action, PermissionAction.ASK)

        # Set session pattern override for cat *
        self.pm.set_session_pattern_override("shell", "cat *", "allow")

        dec_cat1 = self.pm.check_permission("shell", {"command": "cat a.txt"})
        self.assertEqual(dec_cat1.action, PermissionAction.ALLOW)

        dec_cat2 = self.pm.check_permission("shell", {"command": "cat b.txt"})
        self.assertEqual(dec_cat2.action, PermissionAction.ALLOW)

        # Other shell commands still ask
        dec_other = self.pm.check_permission("shell", {"command": "rm a.txt"})
        self.assertEqual(dec_other.action, PermissionAction.ASK)

    def test_config_pattern_rules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "permissions": {
                            "tools": {"shell": "ask", "read": "allow"},
                            "patterns": {
                                "shell": [
                                    {"pattern": "git status*", "action": "allow"},
                                    {"pattern": "rm -rf *", "action": "deny"},
                                ],
                                "read": [
                                    {"pattern": ".env*", "action": "deny"},
                                    {"pattern": "~/.ssh/**", "action": "deny"},
                                ],
                            },
                        }
                    },
                    f,
                )

            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                # Matching allow pattern
                dec1 = self.pm.check_permission("shell", {"command": "git status"})
                self.assertEqual(dec1.action, PermissionAction.ALLOW)

                # Matching deny pattern
                dec2 = self.pm.check_permission("shell", {"command": "rm -rf /tmp"})
                self.assertEqual(dec2.action, PermissionAction.DENY)

                # Read sensitive file -> deny via pattern
                dec_read_env = self.pm.check_permission("read", {"path": "/app/.env"})
                self.assertEqual(dec_read_env.action, PermissionAction.DENY)

                # Read normal file -> allow via tool default
                dec_read_py = self.pm.check_permission("read", {"path": "/app/src/main.py"})
                self.assertEqual(dec_read_py.action, PermissionAction.ALLOW)

    def test_update_pattern_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {}}, f)

            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                self.pm.update_pattern_permission("shell", "cargo test*", "allow")

                dec = self.pm.check_permission("shell", {"command": "cargo test --all"})
                self.assertEqual(dec.action, PermissionAction.ALLOW)

                with open(cfg_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(
                    saved["permissions"]["patterns"]["shell"],
                    [{"pattern": "cargo test*", "action": "allow"}],
                )
