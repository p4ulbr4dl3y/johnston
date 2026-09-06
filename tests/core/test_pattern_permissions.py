import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.domain.policies.permission_policy import (
    PermissionAction,
    evaluate_pattern_rules,
    evaluate_workspace_boundary,
    extract_command_signature,
    extract_shell_subcommands,
    extract_tool_target_values,
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
        self.assertTrue(has_unsafe_shell_syntax("sh script.sh"))
        self.assertTrue(has_unsafe_shell_syntax("echo 'rm -rf /' | sh"))
        self.assertTrue(has_unsafe_shell_syntax("echo 'payload' | bash"))
        self.assertTrue(has_unsafe_shell_syntax("bash < exploit.sh"))
        self.assertTrue(has_unsafe_shell_syntax("base64 -d payload.b64"))
        self.assertTrue(has_unsafe_shell_syntax("base64 --decode payload.b64"))
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

        # Compound: first subcommand uncovered by pattern rules, second is DENY -> must return DENY
        dec_uncovered = evaluate_pattern_rules("shell", {"command": "echo 1 && rm -rf /"}, rules)
        self.assertIsNotNone(dec_uncovered)
        self.assertEqual(dec_uncovered.action, PermissionAction.DENY)

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

    def test_evaluate_pattern_rules_fail_closed_priority(self):
        """Mixed matches resolve DENY > ASK > ALLOW for target-based tools."""
        rules = [
            {"pattern": "*.txt", "action": "allow"},
            {"pattern": "secret*", "action": "deny"},
            {"pattern": "draft*", "action": "ask"},
        ]

        # Both allow and deny match -> deny wins
        dec = evaluate_pattern_rules("read", {"path": "/data/secret.txt"}, rules)
        self.assertEqual(dec.action, PermissionAction.DENY)

        # Both allow and ask match -> ask wins
        dec = evaluate_pattern_rules("read", {"path": "/data/draft.txt"}, rules)
        self.assertEqual(dec.action, PermissionAction.ASK)

        # Only allow matches -> allow
        dec = evaluate_pattern_rules("read", {"path": "/data/notes.txt"}, rules)
        self.assertEqual(dec.action, PermissionAction.ALLOW)

        # Nothing matches -> None (fallback to tool level)
        dec = evaluate_pattern_rules("read", {"path": "/data/image.png"}, rules)
        self.assertIsNone(dec)


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
        self.pm.add_workspace_root("/app")
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


class TestQuotedCompoundRegression(unittest.TestCase):
    """Regression: quotes must protect delimiters in compound splitting."""

    def test_quotes_protect_delimiters(self):
        self.assertEqual(
            extract_shell_subcommands('git commit -m "fix; rm -rf tmp"'),
            ['git commit -m "fix; rm -rf tmp"'],
        )
        self.assertEqual(extract_shell_subcommands("echo 'a && b'"), ["echo 'a && b'"])

    def test_unquoted_compound_still_splits(self):
        self.assertEqual(
            extract_shell_subcommands("git status && pytest -v ; echo done || cat log.txt | grep error"),
            ["git status", "pytest -v", "echo done", "cat log.txt", "grep error"],
        )

    def test_redirections_kept(self):
        self.assertEqual(extract_shell_subcommands("cargo test 2>&1"), ["cargo test 2>&1"])

    def test_escaped_chars_do_not_split(self):
        self.assertEqual(extract_shell_subcommands(r"echo \$HOME; ls"), [r"echo \$HOME", "ls"])

    def test_quoted_allow_pattern_no_false_ask(self):
        """Allowed pattern must match a quoted compound command (no fallback to ASK)."""
        rules = [{"pattern": "git commit *", "action": "allow"}]
        dec = evaluate_pattern_rules("shell", {"command": 'git commit -m "fix; rm -rf tmp"'}, rules)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.action, PermissionAction.ALLOW)


class TestConfigDenyBeatsSessionAllow(unittest.TestCase):
    """Regression: session allow must never bypass an admin-configured deny."""

    def test_config_deny_wins_over_session_allow(self):
        pm = PermissionManager()
        pm.clear_session_overrides()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"permissions": {"patterns": {"read": [{"pattern": ".env*", "action": "deny"}]}}},
                    f,
                )
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                pm.set_session_pattern_override("read", "/app/.env.local", "allow")
                dec = pm.check_permission("read", {"path": "/app/.env.local"})
                self.assertEqual(dec.action, PermissionAction.DENY)

    def test_session_allow_still_overrides_config_ask(self):
        pm = PermissionManager()
        pm.clear_session_overrides()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"permissions": {"patterns": {"shell": [{"pattern": "pytest *", "action": "ask"}]}}},
                    f,
                )
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                pm.set_session_pattern_override("shell", "pytest *", "allow")
                dec = pm.check_permission("shell", {"command": "pytest -v"})
                self.assertEqual(dec.action, PermissionAction.ALLOW)

    def test_config_deny_wins_over_session_tool_override(self):
        """Admin config DENY pattern beats runtime session tool-level allow."""
        pm = PermissionManager()
        pm.clear_session_overrides()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"permissions": {"patterns": {"shell": [{"pattern": "rm -rf *", "action": "deny"}]}}},
                    f,
                )
            with patch("core.permission_manager.CONFIG_FILE", cfg_file):
                pm.set_session_override("shell", "allow")
                dec = pm.check_permission("shell", {"command": "rm -rf /tmp/dangerous"})
                self.assertEqual(dec.action, PermissionAction.DENY)
                self.assertIn("deny", dec.reason.lower())


class TestMultiTargetAndEnhancedSafety(unittest.TestCase):
    def test_extract_tool_target_values_multi(self):
        # Multiple keys
        args = {"source": "/app/src.py", "dest": "/app/dst.py"}
        targets = extract_tool_target_values("create", args)
        self.assertEqual(targets, ["/app/src.py", "/app/dst.py"])

        # List of paths
        args_list = {"paths": ["/app/a.py", "/app/b.py"], "path": "/app/c.py"}
        targets_list = extract_tool_target_values("edit", args_list)
        self.assertEqual(targets_list, ["/app/c.py", "/app/a.py", "/app/b.py"])

        # Shell command
        self.assertEqual(extract_tool_target_values("shell", {"command": "ls -l"}), ["ls -l"])

        # Empty
        self.assertEqual(extract_tool_target_values("edit", {}), [])
        self.assertEqual(extract_tool_target_values("unknown", {"path": "/foo"}), [])

    def test_evaluate_workspace_boundary_multi_target(self):
        with tempfile.TemporaryDirectory() as ws:
            ws_roots = [os.path.realpath(ws)]
            inside1 = os.path.join(ws, "inside1.py")
            inside2 = os.path.join(ws, "inside2.py")
            outside = "/etc/shadow"

            # All inside -> None
            dec = evaluate_workspace_boundary("create", {"source": inside1, "dest": inside2}, ws_roots)
            self.assertIsNone(dec)

            # One outside -> triggers outside action
            dec_out = evaluate_workspace_boundary("create", {"source": inside1, "dest": outside}, ws_roots)
            self.assertIsNotNone(dec_out)
            self.assertEqual(dec_out.action, PermissionAction.ASK)
            self.assertIn("outside workspace", dec_out.reason)

            # Secrets access in secondary target -> DENY
            dec_sec = evaluate_workspace_boundary(
                "edit",
                {"source": inside1, "dest": os.path.expanduser("~/.johnston/secrets.json")},
                ws_roots,
            )
            self.assertIsNotNone(dec_sec)
            self.assertEqual(dec_sec.action, PermissionAction.DENY)

    def test_evaluate_pattern_rules_multi_target(self):
        rules = [
            {"pattern": "/app/src/**", "action": "allow"},
            {"pattern": "/app/secret/**", "action": "deny"},
        ]
        # Both allowed
        dec = evaluate_pattern_rules("create", {"source": "/app/src/a.py", "dest": "/app/src/b.py"}, rules)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.action, PermissionAction.ALLOW)

        # One denied -> DENY
        dec_deny = evaluate_pattern_rules("create", {"source": "/app/src/a.py", "dest": "/app/secret/key.txt"}, rules)
        self.assertIsNotNone(dec_deny)
        self.assertEqual(dec_deny.action, PermissionAction.DENY)

        # One not covered -> None (fallback to tool level)
        dec_uncovered = evaluate_pattern_rules("create", {"source": "/app/src/a.py", "dest": "/var/tmp/x"}, rules)
        self.assertIsNone(dec_uncovered)

    def test_suggest_pattern_safety(self):
        # Unsafe shell command returns None
        self.assertIsNone(suggest_pattern("shell", {"command": "echo bad | sh"}))
        self.assertIsNone(suggest_pattern("shell", {"command": "sh exploit.sh"}))

        # Python interpreter with -m
        self.assertEqual(
            suggest_pattern("shell", {"command": "python -m pytest tests/"}),
            "python -m pytest *",
        )
        # Python inline -c never gets wildcard
        self.assertEqual(
            suggest_pattern("shell", {"command": "python -c 'import sys; print(1)'"}),
            "python -c",
        )

