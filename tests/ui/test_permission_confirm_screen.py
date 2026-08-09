import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from textual.app import App
from textual.widgets import Static

from widgets.screens.permission_confirm import PermissionConfirmScreen


class HostApp(App[None]):
    def __init__(self, screen):
        super().__init__()
        self.scr = screen

    def on_mount(self):
        self.push_screen(self.scr)


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

    def test_build_diff_text_pre_set_diff(self):
        screen = PermissionConfirmScreen("write", {"target_file": "a.py"}, diff="--- custom\n+++ custom")
        self.assertEqual(screen._build_diff_text("a.py"), "--- custom\n+++ custom")

    def test_build_diff_text_create_content(self):
        screen = PermissionConfirmScreen("create", {"target_file": "a.py", "content": "line1\nline2"})
        diff = screen._build_diff_text("a.py")
        self.assertIn("+line1", diff)
        self.assertIn("+line2", diff)
        self.assertIn("@@ -1,2 +1,2 @@", diff)

    def test_build_diff_text_create_empty_content(self):
        screen = PermissionConfirmScreen("write", {"target_file": "a.py", "content": ""})
        diff = screen._build_diff_text("a.py")
        self.assertIn("@@ -1,1 +1,1 @@", diff)
        self.assertEqual(len(diff.splitlines()), 3)

    def test_build_diff_text_edit_chunks(self):
        chunks = [
            {"TargetContent": "old line", "ReplacementContent": "new line", "StartLine": 5},
            {"target_content": "x", "replacement_content": "y", "start_line": 8},
            {"StartLine": 9},
        ]
        screen = PermissionConfirmScreen("multi_edit", {"target_file": "a.py", "replacement_chunks": chunks})
        diff = screen._build_diff_text("a.py")
        self.assertIn("-old line", diff)
        self.assertIn("+new line", diff)
        self.assertIn("@@ -5,1 +5,1 @@", diff)

    def test_build_diff_text_edit_no_content(self):
        screen = PermissionConfirmScreen("edit", {"target_file": "a.py"})
        self.assertEqual(screen._build_diff_text("a.py"), "")

    def test_scroll_actions_swallow_errors(self):
        screen = PermissionConfirmScreen("read", {"path": "foo.py"})
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        screen.action_scroll_up()
        screen.action_scroll_down()
        screen.action_page_up()
        screen.action_page_down()
        screen.action_scroll_left()
        screen.action_scroll_right()


class TestPermissionConfirmScreenPilot(unittest.IsolatedAsyncioTestCase):
    async def test_screen_compose_branches(self):
        tools_to_test = [
            ("shell", {"command": "echo 123"}),
            ("edit", {"target_file": "a.py", "old_string": "a", "new_string": "b"}),
            ("create", {"target_file": "b.py", "content": "print(1)"}),
            ("read", {"path": "c.py"}),
            ("web_fetch", {"url": "https://example.com"}),
            ("invoke_subagent", {"role": "coder", "prompt": "fix bug"}),
            ("manage_shell", {"action": "kill", "task_id": "t1"}),
            ("manage_shell", {"action": "send_input", "task_id": "t1", "input": "hello"}),
            ("other_tool", {"foo": "bar"}),
        ]

        for t_name, t_args in tools_to_test:
            screen = PermissionConfirmScreen(t_name, t_args)
            async with HostApp(screen).run_test() as pilot:
                await pilot.pause()

    async def test_compose_write_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "app.py")
            with open(target, "w", encoding="utf-8") as f:
                f.write("# old content")
            screen = PermissionConfirmScreen("write", {"target_file": target, "content": "print(1)"})
            async with HostApp(screen).run_test() as pilot:
                await pilot.pause()
                self.assertIsNotNone(screen.query_one(Static))

    async def test_compose_subagent_without_prompt(self):
        screen = PermissionConfirmScreen("invoke_subagent", {"role": "coder"})
        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()

    async def test_compose_manage_shell_status_list_other(self):
        cases = [
            {"action": "status", "task_id": "t1"},
            {"action": "list"},
            {"action": "unknown"},
        ]
        for args in cases:
            screen = PermissionConfirmScreen("manage_shell", args)
            async with HostApp(screen).run_test() as pilot:
                await pilot.pause()

    async def test_compose_tool_without_args(self):
        screen = PermissionConfirmScreen("other_tool")
        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()

    async def test_scroll_actions_mounted(self):
        screen = PermissionConfirmScreen(
            "write",
            {"target_file": "a.py"},
            diff="--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new",
        )
        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.action_scroll_up()
            screen.action_scroll_down()
            screen.action_page_up()
            screen.action_page_down()
            screen.action_scroll_left()
            screen.action_scroll_right()

    async def test_action_quit_exits_app(self):
        screen = PermissionConfirmScreen("read", {"path": "foo.py"})
        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()
            with patch.object(screen.app, "exit") as mock_exit:
                screen.action_quit()
                mock_exit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
