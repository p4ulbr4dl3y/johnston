import unittest

from core.shell_guard import analyze_shell_command


class TestShellGuard(unittest.TestCase):
    def test_safe_commands(self):
        safe_cmds = [
            "ls -la",
            "rtk ls -la /Users/yegor/game",
            "rtk find /Users/yegor/game -maxdepth 2",
            "git status",
            "rtk git log -n 5",
            "pytest tests/",
            "cat README.md",
            "echo 'Hello world'",
        ]
        for cmd in safe_cmds:
            is_safe, reason = analyze_shell_command(cmd)
            self.assertTrue(is_safe, f"Expected '{cmd}' to be safe, got reason: {reason}")

    def test_dangerous_commands(self):
        dangerous_cmds = [
            "rm -rf /tmp/foo",
            "rtk rm -f file.txt",
            "del /s /q file.txt",
            "git reset --hard",
            "git push --force",
            "git clean -f",
        ]
        for cmd in dangerous_cmds:
            is_safe, reason = analyze_shell_command(cmd)
            self.assertFalse(is_safe, f"Expected '{cmd}' to be caught as dangerous")


if __name__ == "__main__":
    unittest.main()
