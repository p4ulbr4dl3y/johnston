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

    def test_obfuscation_bypasses_blocked(self):
        bypass_cmds = [
            "sudo -u root rm -rf /",
            "sudo -i rm -rf /",
            "env -i rm -rf /tmp/x",
            "echo $(rm -rf /)",
            "echo `rm -rf /`",
            "echo /tmp/x | xargs rm -rf",
            "sh -c \"rm -rf /\"",
            "bash -c 'rm -rf /'",
            "python -c \"import shutil; shutil.rmtree('/tmp')\"",
            "find . -delete",
            "git push --force",
        ]
        for cmd in bypass_cmds:
            is_safe, reason = analyze_shell_command(cmd)
            self.assertFalse(is_safe, f"Expected '{cmd}' to be caught, got: {reason}")

    def test_legit_commands_still_safe(self):
        safe_cmds = [
            "ls -la",
            "rtk git status",
            "git diff HEAD",
            "pytest tests/ -q",
            "cat README.md",
            "rtk find . -name '*.py'",
            "python --version",
            "echo hello world",
        ]
        for cmd in safe_cmds:
            is_safe, reason = analyze_shell_command(cmd)
            self.assertTrue(is_safe, f"Expected '{cmd}' to be safe, got: {reason}")


if __name__ == "__main__":
    unittest.main()
