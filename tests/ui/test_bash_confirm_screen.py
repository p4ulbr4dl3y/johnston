import unittest

from widgets.screens.bash_confirm import BashConfirmScreen


class TestBashConfirmScreen(unittest.TestCase):
    def test_screen_initialization(self):
        screen = BashConfirmScreen("rm -rf /tmp/test", "Execution of potentially unsafe command: rm")
        self.assertEqual(screen.command, "rm -rf /tmp/test")
        self.assertEqual(screen.reason, "Execution of potentially unsafe command: rm")
        self.assertIn("enter", [b[0] for b in screen.BINDINGS])
        self.assertIn("escape", [b[0] for b in screen.BINDINGS])


if __name__ == "__main__":
    unittest.main()
