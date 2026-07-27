import unittest

from core.shell_guard import analyze_bash_command


class TestBashGuard(unittest.TestCase):
    def test_safe_commands(self):
        safe_cmds = [
            "ls -la",
            "pwd",
            "cat README.md",
            "grep -rn 'foo' .",
            "git status",
            "git diff HEAD",
            "git log -n 5",
            "git commit -m 'feat: new stuff'",
            "git checkout -b feature",
            "python main.py",
            "uv run pytest",
            "npm install",
            "echo 'secret' > .env",
            "echo $(whoami)",
            "make build",
        ]
        for cmd in safe_cmds:
            is_safe, reason = analyze_bash_command(cmd)
            self.assertTrue(is_safe, f"Should be safe: {cmd} (reason: {reason})")

    def test_risky_commands(self):
        risky_cmds = [
            ("rm -rf /tmp/foo", "rm"),
            ("git push origin main", "Git"),
            ("git reset --hard", "Git"),
            ("git clean -fd", "Git"),
            ("sudo apt update", "sudo"),
            ("ls && rm -rf .", "rm"),
            ("cat /etc/passwd", "/etc"),
            ("chmod +x script.sh", "chmod"),
        ]
        for cmd, expected_substring in risky_cmds:
            is_safe, reason = analyze_bash_command(cmd)
            self.assertFalse(is_safe, f"Should be risky: {cmd}")
            self.assertIn(expected_substring.lower(), reason.lower())


if __name__ == "__main__":
    unittest.main()
