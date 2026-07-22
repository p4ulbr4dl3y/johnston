import unittest

from widgets.screens.bash_confirm import BashConfirmScreen


class TestBashConfirmScreen(unittest.TestCase):
    def test_screen_initialization(self):
        screen = BashConfirmScreen("rm -rf /tmp/test", "Выполнение потенц. опасной команды: rm")
        self.assertEqual(screen.command, "rm -rf /tmp/test")
        self.assertEqual(screen.reason, "Выполнение потенц. опасной команды: rm")
        self.assertIn("enter", [b[0] for b in screen.BINDINGS])
        self.assertIn("escape", [b[0] for b in screen.BINDINGS])


if __name__ == "__main__":
    unittest.main()
