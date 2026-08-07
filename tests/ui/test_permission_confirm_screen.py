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


class TestPermissionConfirmScreenPilot(unittest.IsolatedAsyncioTestCase):
    async def test_screen_compose_branches(self):
        from textual.app import App

        class HostApp(App[None]):
            def __init__(self, screen):
                super().__init__()
                self.scr = screen

            def on_mount(self):
                self.push_screen(self.scr)

        tools_to_test = [
            ("shell", {"command": "echo 123"}),
            ("edit", {"target_file": "a.py", "old_string": "a", "new_string": "b"}),
            ("create", {"target_file": "b.py", "content": "print(1)"}),
            ("read", {"path": "c.py"}),
            ("web_fetch", {"url": "https://example.com"}),
            ("invoke_subagent", {"role": "coder", "prompt": "fix bug"}),
            ("manage_task", {"action": "kill", "task_id": "t1"}),
            ("manage_task", {"action": "send_input", "task_id": "t1", "input": "hello"}),
            ("other_tool", {"foo": "bar"}),
        ]

        for t_name, t_args in tools_to_test:
            screen = PermissionConfirmScreen(t_name, t_args)
            app = HostApp(screen)
            async with app.run_test() as pilot:
                await pilot.pause()


if __name__ == "__main__":
    unittest.main()
