import unittest

from widgets.screens.shell_confirm import BashConfirmScreen, ShellConfirmScreen


class TestShellConfirmScreen(unittest.TestCase):
    def test_screen_initialization(self):
        screen = ShellConfirmScreen("rm -rf /tmp/test", "Execution of potentially unsafe command: rm")
        self.assertEqual(screen.command, "rm -rf /tmp/test")
        self.assertIn("rm", screen.reason)

    def test_backward_compatibility_alias(self):
        self.assertIs(BashConfirmScreen, ShellConfirmScreen)


if __name__ == "__main__":
    unittest.main()
