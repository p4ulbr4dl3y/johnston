import unittest

from widgets.presentation.screens.permission_confirm import PermissionConfirmScreen


class TestShellConfirmScreen(unittest.TestCase):
    def test_screen_initialization(self):
        screen = PermissionConfirmScreen(
            tool_name="shell",
            args={"command": "rm -rf /tmp/test"},
        )
        self.assertEqual(screen.tool_name, "shell")
        self.assertEqual(screen.args["command"], "rm -rf /tmp/test")


if __name__ == "__main__":
    unittest.main()
