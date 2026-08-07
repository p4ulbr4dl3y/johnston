import unittest

from widgets.screens.permission_confirm import PermissionConfirmScreen


class TestPermissionConfirmScreen(unittest.TestCase):
    def test_screen_initialization_write(self):
        screen = PermissionConfirmScreen(
            tool_name="write",
            args={"target_file": "src/app.py"},
            reason="Update entrypoint",
            diff="--- a\n+++ b",
        )
        self.assertEqual(screen.tool_name, "write")
        self.assertEqual(screen.args["target_file"], "src/app.py")

    def test_screen_actions(self):
        screen = PermissionConfirmScreen("read", {"path": "foo.py"})
        dismissed_val = None

        def mock_dismiss(result):
            nonlocal dismissed_val
            dismissed_val = result

        screen.dismiss = mock_dismiss

        screen.action_approve()
        self.assertEqual(dismissed_val, "allow")

        screen.action_always_allow()
        self.assertEqual(dismissed_val, "always_allow")

        screen.action_deny()
        self.assertEqual(dismissed_val, "deny")


if __name__ == "__main__":
    unittest.main()
