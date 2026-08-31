import os
import tempfile
import unittest
from unittest.mock import MagicMock

from textual.app import App
from textual.widgets import Static

from widgets.presentation.screens.permission_confirm import PermissionConfirmScreen


class HostApp(App[None]):
    def __init__(self, screen):
        super().__init__()
        self.scr = screen

    def on_mount(self):
        self.push_screen(self.scr)


class TestPermissionConfirmScreen(unittest.TestCase):
    def test_screen_initialization_create(self):
        screen = PermissionConfirmScreen(
            tool_name="create",
            args={"path": "src/app.py"},
            diff="--- a\n+++ b",
        )
        self.assertEqual(screen.tool_name, "create")
        self.assertEqual(screen.args["path"], "src/app.py")

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

    def test_screen_action_allow_pattern(self):
        screen = PermissionConfirmScreen("shell", {"command": "git status"})
        dismissed_val = None

        def mock_dismiss(result):
            nonlocal dismissed_val
            dismissed_val = result

        screen.dismiss = mock_dismiss
        self.assertEqual(screen.suggested_pattern, "git status *")
        screen.action_allow_pattern()
        self.assertEqual(dismissed_val, "pattern:git status *")

        # Fallback when no pattern suggested
        screen_no_pat = PermissionConfirmScreen("ask_user", {})
        screen_no_pat.dismiss = mock_dismiss
        screen_no_pat.action_allow_pattern()
        self.assertEqual(dismissed_val, "always_allow")


    def test_build_diff_text_pre_set_diff(self):
        screen = PermissionConfirmScreen("create", {"path": "a.py"}, diff="--- custom\n+++ custom")
        self.assertEqual(screen._build_diff_text("a.py"), "--- custom\n+++ custom")

    def test_build_diff_text_create_content(self):
        screen = PermissionConfirmScreen("create", {"path": "a.py", "content": "line1\nline2"})
        diff = screen._build_diff_text("a.py")
        self.assertIn("+line1", diff)
        self.assertIn("+line2", diff)
        self.assertIn("@@ -1,2 +1,2 @@", diff)

    def test_build_diff_text_create_empty_content(self):
        screen = PermissionConfirmScreen("create", {"path": "a.py", "content": ""})
        diff = screen._build_diff_text("a.py")
        self.assertIn("@@ -1,1 +1,1 @@", diff)
        self.assertEqual(len(diff.splitlines()), 3)

    def test_build_diff_text_edit(self):
        screen = PermissionConfirmScreen("edit", {"path": "a.py", "old_str": "old line", "new_str": "new line"})
        diff = screen._build_diff_text("a.py")
        self.assertIn("-old line", diff)
        self.assertIn("+new line", diff)

    def test_build_diff_text_edit_no_content(self):
        screen = PermissionConfirmScreen("edit", {"path": "a.py"})
        self.assertEqual(screen._build_diff_text("a.py"), "")

    def test_scroll_actions_swallow_errors(self):
        screen = PermissionConfirmScreen("read", {"path": "foo.py"})
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        screen.action_page_up()
        screen.action_page_down()


class TestPermissionConfirmScreenPilot(unittest.IsolatedAsyncioTestCase):
    async def test_screen_compose_branches(self):
        tools_to_test = [
            ("shell", {"command": "echo 123"}),
            ("edit", {"path": "a.py", "old_str": "a", "new_str": "b"}),
            ("create", {"path": "b.py", "content": "print(1)"}),
            ("read", {"path": "c.py"}),
            ("web_fetch", {"url": "https://example.com"}),
            ("invoke_subagent", {"title": "Task 1", "role": "coder", "prompt": "fix bug"}),
            ("invoke_subagent", {"type": "worker"}),
            ("manage_shell", {"action": "kill", "task_id": "t1"}),
            ("manage_shell", {"action": "send_input", "task_id": "t1", "input": "hello"}),
            ("manage_subagent", {"action": "list"}),
            ("manage_subagent", {"action": "kill", "session_id": "s1"}),
            ("manage_subagent", {"action": "send_message", "session_id": "s1", "message": "hello sub"}),
            ("update_plan", {"explanation": "step 1", "plan": [{"step": "Step one", "status": "completed"}]}),
            ("update_plan", {"plan": "1. Step one\n2. Step two"}),
            ("ask_user", {"questions": [{"question": "Q1", "options": ["opt1", "opt2"]}]}),
            ("ask_user", {"questions": ["Q1", "Q2"]}),
            ("ask_user", {"questions": ["Single Q"]}),
            ("other_tool", {"foo": "bar"}),
        ]

        for t_name, t_args in tools_to_test:
            screen = PermissionConfirmScreen(t_name, t_args)
            async with HostApp(screen).run_test() as pilot:
                await pilot.pause()

    async def test_compose_create_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "app.py")
            with open(target, "w", encoding="utf-8") as f:
                f.write("# old content")
            screen = PermissionConfirmScreen("create", {"path": target, "content": "print(1)"})
            async with HostApp(screen).run_test() as pilot:
                await pilot.pause()
                self.assertIsNotNone(screen.query_one(Static))

    async def test_compose_subagent_without_prompt(self):
        screen = PermissionConfirmScreen("invoke_subagent", {"role": "coder"})
        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()

    async def test_compose_subagent_actor_prefix(self):
        screen = PermissionConfirmScreen("edit", {"path": "main.py"}, is_subagent=True)
        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()
            mds = screen.query("Markdown")
            all_md = "\n".join(str(getattr(m, "_markdown", "")) for m in mds)
            self.assertIn("Subagent wants to edit", all_md)

    async def test_compose_manage_shell_list_other(self):
        cases = [
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
            "create",
            {"path": "a.py"},
            diff="--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new",
        )
        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.action_page_up()
            screen.action_page_down()

    def test_hint_text_adaptation(self):
        # Hint text is unified with OptionList and collapses below BREAKPOINT_HINT (60)
        screen = PermissionConfirmScreen("read", {})
        self.assertIn("enter: select", screen._build_hint_text(width=80))
        self.assertIn("r: feedback", screen._build_hint_text(width=80))
        compact = screen._build_hint_text(width=40)
        self.assertIn("enter", compact)
        self.assertIn("r", compact)
        self.assertNotIn("enter: select", compact)

    async def test_reject_with_reason_flow(self):
        screen = PermissionConfirmScreen("shell", {"command": "rm -rf tmp"})
        dismissed_val = None

        def mock_dismiss(result):
            nonlocal dismissed_val
            dismissed_val = result

        screen.dismiss = mock_dismiss

        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()
            inp = screen.query_one("#reject-reason-input")
            self.assertFalse(inp.display)

            # Trigger reject with reason
            screen.action_reject_with_reason()
            await pilot.pause()
            self.assertTrue(inp.display)
            self.assertTrue(inp.has_focus)

            # Type and submit reason
            inp.value = "do not delete"
            screen.on_input_submitted(MagicMock(input=inp, value="do not delete"))
            self.assertEqual(dismissed_val, "deny:do not delete")

    async def test_reject_with_reason_cancel_esc(self):
        screen = PermissionConfirmScreen("shell", {"command": "rm -rf tmp"})
        dismissed_val = None

        def mock_dismiss(result):
            nonlocal dismissed_val
            dismissed_val = result

        screen.dismiss = mock_dismiss

        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()
            inp = screen.query_one("#reject-reason-input")

            # Open reason input
            screen.action_reject_with_reason()
            await pilot.pause()
            self.assertTrue(inp.display)

            # Press deny / esc -> dismisses modal with deny
            screen.action_deny()
            self.assertEqual(dismissed_val, "deny")

    async def test_reject_reason_input_navigation_keys(self):
        diff = "\n".join(f"+line {i}" for i in range(50))
        screen = PermissionConfirmScreen("edit", {"path": "large.py"}, diff=diff)
        async with HostApp(screen).run_test() as pilot:
            await pilot.pause()
            screen.action_reject_with_reason()
            await pilot.pause()
            inp = screen.query_one("#reject-reason-input")
            self.assertTrue(inp.has_focus)

            # Test up/down navigation keys returning to options list
            screen.focus_options_list = MagicMock()
            screen.focus_first_option = MagicMock()

            from textual.events import Key

            await inp._on_key(Key("up", "up"))
            screen.focus_options_list.assert_called_once()

            await inp._on_key(Key("down", "down"))
            screen.focus_first_option.assert_called_once()


    async def test_update_plan_descriptions(self):
        screen_with_exp = PermissionConfirmScreen("update_plan", {"explanation": "Refactor auth flow"})
        async with HostApp(screen_with_exp).run_test() as pilot:
            await pilot.pause()
            mds = screen_with_exp.query("Markdown")
            all_md = "\n".join(str(getattr(m, "_markdown", "")) for m in mds)
            self.assertIn('Agent wants to update the plan: "Refactor auth flow"', all_md)

        screen_no_exp = PermissionConfirmScreen("update_plan", {})
        async with HostApp(screen_no_exp).run_test() as pilot:
            await pilot.pause()
            mds = screen_no_exp.query("Markdown")
            all_md = "\n".join(str(getattr(m, "_markdown", "")) for m in mds)
            self.assertIn("Agent wants to update the plan", all_md)

    async def test_ask_user_descriptions(self):
        screen_multi = PermissionConfirmScreen(
            "ask_user",
            {"questions": [{"question": "Choose branch"}, {"question": "Apply migrations?"}]},
        )
        async with HostApp(screen_multi).run_test() as pilot:
            await pilot.pause()
            mds = screen_multi.query("Markdown")
            all_md = "\n".join(str(getattr(m, "_markdown", "")) for m in mds)
            self.assertIn("Agent wants to ask: `Choose branch`, `Apply migrations?`", all_md)

        screen_plain = PermissionConfirmScreen("ask_user", {"questions": ["Single question?"]})
        async with HostApp(screen_plain).run_test() as pilot:
            await pilot.pause()
            mds = screen_plain.query("Markdown")
            all_md = "\n".join(str(getattr(m, "_markdown", "")) for m in mds)
            self.assertIn("Agent wants to ask: `Single question?`", all_md)

        screen_empty = PermissionConfirmScreen("ask_user", {})
        async with HostApp(screen_empty).run_test() as pilot:
            await pilot.pause()
            mds = screen_empty.query("Markdown")
            all_md = "\n".join(str(getattr(m, "_markdown", "")) for m in mds)
            self.assertIn("Agent wants to ask a question", all_md)

    def test_content_width_calculation_shell(self):
        screen_short = PermissionConfirmScreen("shell", {"command": "git status"})
        w_short = screen_short._calculate_content_width()
        self.assertGreaterEqual(w_short, 40)
        self.assertLess(w_short, 70)

        screen_med = PermissionConfirmScreen(
            "shell",
            {"command": "uv run pytest -n auto -m 'not slow' --cov=core"},
        )
        w_med = screen_med._calculate_content_width()
        self.assertGreater(w_med, w_short)
        self.assertLessEqual(w_med, 80)

        screen_long = PermissionConfirmScreen("shell", {"command": "x" * 150})
        w_long = screen_long._calculate_content_width()
        self.assertGreater(w_long, 100)

    def test_content_width_calculation_subagent_prompt_capped(self):
        screen_prompt = PermissionConfirmScreen(
            "invoke_subagent",
            {
                "title": "Audit permission handlers",
                "type": "Codebase Researcher",
                "prompt": "Analyze all references to PermissionConfirmScreen across tests and widgets.",
            },
        )
        w = screen_prompt._calculate_content_width()
        # Text descriptions and prompts are capped to ~64 + gutter, avoiding 100+ ballooning
        self.assertLessEqual(w, 75)
        self.assertGreaterEqual(w, 40)

    async def test_adaptive_modal_width_applied_on_mount(self):
        screen = PermissionConfirmScreen("shell", {"command": "git status"})
        async with HostApp(screen).run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            dialog = screen.query_one("#modal-dialog")
            # Should hug content rather than stretching to 104
            self.assertIsNotNone(dialog.styles.width)
            self.assertLessEqual(dialog.styles.width.value, 70)
            self.assertGreaterEqual(dialog.styles.width.value, 40)


if __name__ == "__main__":
    unittest.main()
