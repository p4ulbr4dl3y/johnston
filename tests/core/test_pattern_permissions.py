import json
import os
import tempfile
import unittest
from unittest.mock import patch

from johnston_core.domain.policies.permission_policy import (
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
from johnston_core.permission_manager import PermissionManager


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
        self.assertTrue(has_unsafe_shell_syntax("python -c 'print(1)'"))
        self.assertTrue(has_unsafe_shell_syntax("python3.10 -c 'import os'"))
        self.assertTrue(has_unsafe_shell_syntax("python3 -Bc 'import sys'"))
        self.assertTrue(has_unsafe_shell_syntax("python -u -c 'import sys'"))
        self.assertTrue(has_unsafe_shell_syntax("node -e 'process.exit(0)'"))
        self.assertTrue(has_unsafe_shell_syntax("node --eval 'process.exit(0)'"))
        self.assertTrue(has_unsafe_shell_syntax("ruby -e 'puts 1'"))
        self.assertTrue(has_unsafe_shell_syntax("perl -e 'print 1'"))
        self.assertTrue(has_unsafe_shell_syntax("echo 'payload' | python3"))
        self.assertTrue(has_unsafe_shell_syntax("echo 'payload' | node"))
        self.assertFalse(has_unsafe_shell_syntax("python -m pytest tests/"))
        self.assertFalse(has_unsafe_shell_syntax("python -u script.py"))
        self.assertFalse(has_unsafe_shell_syntax("python script.py"))
        self.assertFalse(has_unsafe_shell_syntax("git status"))
        self.assertFalse(has_unsafe_shell_syntax("cat foo.txt && pytest -k test_foo"))

    def test_unsafe_shell_env_prefixed_interpreter(self):
        """Env-prefixed interpreter launches are unsafe (startup file injection)."""
        for cmd in (
            "BASH_ENV=/tmp/evil.sh bash",
            "ENV=/tmp/e sh",
            "ZDOTDIR=/tmp/x zsh",
            "NODE_OPTIONS=--require=/tmp/e.js node --version",
            "PYTHONSTARTUP=/tmp/e.py python",
            "RUBYOPT=-r/tmp/e.rb ruby -v",
            "FOO=1 bash",
            "A=1 B=2 bash",
            "env bash",
            "env -i python",
            "NODE_OPTIONS=--env-file=/tmp/e node x.js",
            "BASH_ENV=/tmp/e.sh; bash",
        ):
            self.assertTrue(
                has_unsafe_shell_syntax(cmd),
                f"env-prefixed interpreter must be unsafe: {cmd!r}",
            )

    def test_unsafe_shell_combined_flags(self):
        """Combined/login/script flags switch the interpreter to code mode."""
        for cmd in (
            "bash -lc 'ls'",
            "bash --login -c 'ls'",
            "sh -ec 'ls'",
            "zsh -fc 'ls'",
            "dash -sc 'ls'",
            "bash -li 'ls'",
            "python3.13 --no-user-site -c 'x'",
        ):
            self.assertTrue(
                has_unsafe_shell_syntax(cmd),
                f"combined-flag interpreter must be unsafe: {cmd!r}",
            )

    def test_safe_interpreter_invocations_stay_safe(self):
        """Deterministic interpreter invocations (module/script) stay safe."""
        for cmd in (
            "python -m pytest tests/",
            "python3.12 -m pytest -q",
            "python -u script.py",
            "python script.py",
        ):
            self.assertFalse(
                has_unsafe_shell_syntax(cmd),
                f"deterministic interpreter invocation must stay safe: {cmd!r}",
            )

    def test_unsafe_shell_osascript_and_awk(self):
        """Regression: code-executing interpreters invoked via -e / system()
        must be flagged unsafe even though they are not shells."""
        for cmd in (
            "osascript -e 'do shell script \"id\"'",
            "/usr/bin/osascript -e 'tell app \"Finder\" to quit'",
            "osascript  -e 'return 1'",
            "awk 'BEGIN{system(\"rm -rf /tmp/x\")}'",
            "gawk '{system(\"id\")}'",
            "mawk 'END{system(\"whoami\")}'",
            "awk '{print 1; system(\"rm -rf /\"); print 2}'",
            "echo x | gawk -v cmd=id '{system(cmd)}'",
        ):
            self.assertTrue(
                has_unsafe_shell_syntax(cmd),
                f"code-executing interpreter must be unsafe: {cmd!r}",
            )

    def test_osascript_without_code_flag_stays_safe(self):
        """osascript launching a compiled app/script (no -e) stays safe."""
        for cmd in (
            "osascript my.scpt",
            "osascript -l JavaScript script.js",
        ):
            self.assertFalse(
                has_unsafe_shell_syntax(cmd),
                f"non-code osascript invocation must stay safe: {cmd!r}",
            )

    def test_strip_command_wrappers(self):
        import shlex

        from johnston_core.domain.policies.policy_shell import strip_command_wrappers

        self.assertEqual(strip_command_wrappers("sudo rm -rf /tmp/x"), "rm -rf /tmp/x")
        self.assertEqual(strip_command_wrappers("env FOO=1 sudo git status"), "git status")
        # Pipes are not wrappers: token set preserved (shlex round-trip may re-quote '|').
        self.assertEqual(
            shlex.split(strip_command_wrappers("echo x | xargs rm -rf")),
            ["echo", "x", "|", "xargs", "rm", "-rf"],
        )
        self.assertEqual(strip_command_wrappers("sudo -u root whoami"), "whoami")
        self.assertEqual(strip_command_wrappers("xargs rm -rf"), "rm -rf")
        self.assertEqual(strip_command_wrappers(""), "")
        self.assertEqual(strip_command_wrappers("git status"), "git status")

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
        self.assertIsNone(suggest_pattern("shell", {"command": "python -c 'print(1)'"}))
        self.assertEqual(suggest_pattern("shell", {"command": "python -m pytest tests/"}), "python -m pytest *")

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

            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
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
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                pm.set_session_pattern_override("read", "/app/.env.local", "allow")
                dec = pm.check_permission("read", {"path": "/app/.env.local"})
                self.assertEqual(dec.action, PermissionAction.DENY)

    def test_wrapper_commands_do_not_bypass_shell_deny_patterns(self):
        """Regression: sudo/env/xargs-wrapped commands must still match DENY patterns
        (deny matching runs against the wrapper-stripped command too)."""
        pm = PermissionManager()
        pm.clear_session_overrides()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "permissions": {
                            "tools": {"shell": "allow"},
                            "patterns": {"shell": [{"pattern": "rm -rf *", "action": "deny"}]},
                        }
                    },
                    f,
                )
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                for cmd in (
                    "rm -rf /tmp/x",
                    "sudo rm -rf /tmp/x",
                    "env rm -rf /tmp/x",
                    "echo x | xargs rm -rf",
                    "xargs rm -rf",
                    "sudo -u root rm -rf /tmp/x",
                    # Regression: POSIX-only prefix wrappers must not hide a deny.
                    "builtin rm -rf /tmp/x",
                    "command rm -rf /tmp/x",
                    "builtin command rm -rf /tmp/x",
                    # Regression: xargs placeholder flags consume their arg and
                    # must not leave the real command stripped away.
                    "xargs -I {} rm -rf /tmp/x",
                    "xargs -I{} rm -rf /tmp/x",
                    "xargs -L 5 rm -rf /tmp/x",
                    "xargs -n 1 rm -rf /tmp/x",
                    "sudo -n rm -rf /tmp/x",  # -n takes no arg: keep the command
                ):
                    dec = pm.check_permission("shell", {"command": cmd})
                    self.assertEqual(
                        dec.action,
                        PermissionAction.DENY,
                        f"wrapper must not bypass deny pattern: {cmd!r}",
                    )

    def test_wrapper_command_allow_pattern_matches_stripped(self):
        """Session pattern allow on the stripped command still applies under a wrapper."""
        pm = PermissionManager()
        pm.clear_session_overrides()
        pm.set_session_pattern_override("shell", "git status *", "allow")
        dec = pm.check_permission("shell", {"command": "sudo git status"})
        self.assertEqual(dec.action, PermissionAction.ALLOW)

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
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
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
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                pm.set_session_override("shell", "allow")
                dec = pm.check_permission("shell", {"command": "rm -rf /tmp/dangerous"})
                self.assertEqual(dec.action, PermissionAction.DENY)
                self.assertIn("deny", dec.reason.lower())

    def test_config_tool_deny_wins_over_session_pattern_allow(self):
        """Regression: explicit config tool-level DENY beats session pattern allow."""
        pm = PermissionManager()
        pm.clear_session_overrides()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"permissions": {"tools": {"shell": "deny", "read": "deny"}}},
                    f,
                )
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                pm.set_session_pattern_override("shell", "ls *", "allow")
                dec = pm.check_permission("shell", {"command": "ls -la"})
                self.assertEqual(dec.action, PermissionAction.DENY)

                pm2 = PermissionManager()
                pm2.clear_session_overrides()
                pm2.set_session_pattern_override("read", "/etc/hosts", "allow")
                dec3 = pm2.check_permission("read", {"path": "/etc/hosts"})
                self.assertEqual(dec3.action, PermissionAction.DENY)

    def test_config_tool_deny_is_overridden_by_explicit_session_tool_override(self):
        """Documented contract: explicit session tool-level override beats config tool deny."""
        pm = PermissionManager()
        pm.clear_session_overrides()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"shell": "deny"}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                pm.set_session_override("shell", "allow")
                dec = pm.check_permission("shell", {"command": "ls -la"})
                self.assertEqual(dec.action, PermissionAction.ALLOW)
                self.assertIn("Session override", dec.reason)

                pm.set_session_override("shell", "ask")
                dec2 = pm.check_permission("shell", {"command": "ls -la"})
                self.assertEqual(dec2.action, PermissionAction.ASK)

    def test_config_tool_deny_wins_over_session_pattern_allow_unsafe_shell(self):
        """Regression: config tool deny also blocks env-prefixed interpreter launches."""
        pm = PermissionManager()
        pm.clear_session_overrides()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"tools": {"shell": "deny"}}}, f)
            with patch("johnston_core.permission_manager.CONFIG_FILE", cfg_file):
                pm.set_session_pattern_override("shell", "bash *", "allow")
                dec = pm.check_permission("shell", {"command": "BASH_ENV=/tmp/evil.sh bash"})
                self.assertEqual(dec.action, PermissionAction.DENY)


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
        # Python inline -c is unsafe and returns None (no pattern auto-allow)
        self.assertIsNone(
            suggest_pattern("shell", {"command": "python -c 'import sys; print(1)'"}),
        )

