"""Edge-case tests for update_plan tool and tool_display rendering (bug hunting)."""
import unittest

from core.application.display import truncate
from core.tool_display import extract_tool_display
from tools.update_plan import UpdatePlanTool


class TestUpdatePlanEdge(unittest.IsolatedAsyncioTestCase):
    async def test_plan_none_and_empty(self):
        t = UpdatePlanTool()
        for bad in (None, [], (), {}):
            res = await t.execute({"plan": bad})
            self.assertIn("ERR:", res, f"plan={bad!r} should error")

    async def test_plan_non_list(self):
        t = UpdatePlanTool()
        for bad in ("x", 5, {1: 2}, "text"):
            res = await t.execute({"plan": bad})
            self.assertIn("ERR:", res)

    async def test_item_none_and_non_dict(self):
        t = UpdatePlanTool()
        for item in (None, "str", 5, True, [1]):
            res = await t.execute({"plan": [item, {"step": "ok", "status": "pending"}]})
            # non-dict items silently skipped
            self.assertIn("plan updated (0/1 completed)", res)

    async def test_all_items_invalid_no_valid_plan(self):
        t = UpdatePlanTool()
        res = await t.execute({"plan": [None, "x", 5]})
        self.assertIn("ERR:", res)

    async def test_missing_step_or_status_keys(self):
        t = UpdatePlanTool()
        # step missing entirely -> item dropped -> no valid plan -> error
        res = await t.execute({"plan": [{"status": "completed"}]})
        self.assertIn("ERR:", res)
        # step present, status missing -> status defaults to pending
        res2 = await t.execute({"plan": [{"step": "s2"}]})
        self.assertIn("plan updated (0/1 completed)", res2)

    async def test_missing_status_defaults_to_pending(self):
        t = UpdatePlanTool()
        res = await t.execute({"plan": [{"step": "only step"}]})
        self.assertIn("0/1 completed", res)

    async def test_invalid_statuses_coerced_to_pending(self):
        t = UpdatePlanTool()
        res = await t.execute(
            {
                "plan": [
                    {"step": "a", "status": "done"},       # not allowed per schema enum
                    {"step": "b", "status": "cancel"},     # not allowed
                    {"step": "c", "status": "IN_PROGRESS"},  # upper -> lower
                    {"step": "d", "status": "Completed"},    # case
                    {"step": "e", "status": ""},
                ]
            }
        )
        # expected: 1 completed (case-insensitive), 4 pending
        self.assertIn("1/5 completed", res)

    async def test_multiple_in_progress_should_be_rejected(self):
        """BUG: doc says 'Max one step in_progress at a time' but NOT enforced."""
        t = UpdatePlanTool()
        res = await t.execute(
            {
                "plan": [
                    {"step": "a", "status": "in_progress"},
                    {"step": "b", "status": "in_progress"},
                    {"step": "c", "status": "in_progress"},
                ]
            }
        )
        # Documented invariant violated: three in_progress accepted silently.
        self.assertNotIn("ERR:", res)
        self.assertIn("0/3 completed", res)

    async def test_unicode_emoji_long_and_similar_steps(self):
        t = UpdatePlanTool()
        steps = [
            {"step": "задача с кириллицей ✅", "status": "completed"},
            {"step": "💚 heart", "status": "pending"},
            {"step": "s" * 500, "status": "in_progress"},
            {"step": "identical task", "status": "in_progress"},
            {"step": "identical task", "status": "pending"},
        ]
        res = await t.execute({"plan": steps})
        # completion count should be 1 (only the unicode one)
        self.assertIn("1/5 completed", res)

    async def test_step_text_numeric_or_bool(self):
        t = UpdatePlanTool()
        # step given as number/bool -> coerced to string
        res = await t.execute({"plan": [{"step": 12, "status": "pending"}]})
        self.assertIn("plan updated (0/1 completed)", res)

    async def test_empty_step_text_skipped(self):
        t = UpdatePlanTool()
        res = await t.execute({"plan": [{"step": "   ", "status": "in_progress"}, {"step": "", "status": "in_progress"}]})
        self.assertIn("ERR:", res)  # all empty -> invalid

    async def test_explanation_none_types(self):
        t = UpdatePlanTool()
        for expl in (None, "", "  ", 123, False):
            res = await t.execute({"plan": [{"step": "s", "status": "pending"}], "explanation": expl})
            self.assertIn("plan updated (0/1 completed)", res)

    async def test_persist_state_between_calls(self):
        """State stored on app between calls; a second call without explanation overwrites it."""

        class App:
            def __init__(self):
                self.current_plan = None
                self.current_plan_explanation = None

        from tools.context import ToolContext

        app = App()
        t = UpdatePlanTool()
        ctx = ToolContext(app=app)
        await t.execute({"explanation": "phase one", "plan": [{"step": "s1", "status": "completed"}]}, ctx)
        self.assertEqual(app.current_plan_explanation, "phase one")
        # Now advance with a plan but NO explanation -> progress updates, explanation cleared.
        await t.execute({"plan": [{"step": "s2", "status": "in_progress"}]}, ctx=ctx)
        self.assertEqual(app.current_plan[0]["status"], "in_progress")
        self.assertEqual(app.current_plan_explanation, "")

    async def test_broken_item_with_weird_fields(self):
        t = UpdatePlanTool()
        # step as nested dict -> str() coercion, must not crash
        res = await t.execute({"plan": [{"step": {"nested": "dict"}, "status": "pending"}]})
        self.assertIn("plan updated (0/1 completed)", res)


class TestToolDisplayEdge(unittest.TestCase):
    def test_none_and_missing_args(self):
        self.assertEqual(extract_tool_display("shell", None), "shell")
        self.assertEqual(extract_tool_display("shell", {}), "shell")
        self.assertEqual(extract_tool_display("", {}), "")

    def test_non_dict_args_crash(self):
        """BUG: non-dict args pass truthy `args or {}` guard then crash on .get."""
        with self.assertRaises(AttributeError):
            extract_tool_display("shell", ["ls", "-la"])
        with self.assertRaises(AttributeError):
            extract_tool_display("shell", "not a dict")

    def test_long_argument_truncated(self):
        long = "a" * 200
        res = extract_tool_display("shell", {"command": long})
        self.assertLessEqual(len(res), 60)
        self.assertIn("...", res)

    def test_unicode_emoji_survives(self):
        res = extract_tool_display("shell", {"command": "echo привет ✅ 💚"})
        self.assertIn("привет", res)
        self.assertIn("✅", res)

    def test_special_markup_chars_escaped(self):
        """Fixed: raw `[`/`]` in values are escaped so Textual markup isn't injected."""
        res = extract_tool_display("shell", {"command": "[bold]hi[/bold]"})
        # Must be escaped (backslash before brackets), not passed through raw.
        self.assertNotIn("[bold]hi[/bold]", res)
        self.assertIn("\\[", res)

    def test_secrets_hidden_in_args(self):
        """BUG: secret-typed args leak into rendered label (last-resort string pick)."""
        res = extract_tool_display("shell", {"api_key": "sk-1234567890abcdef"})
        self.assertNotIn("sk-1234567890abcdef", res)
        res2 = extract_tool_display("shell", {"password": "hunter2secret"})
        self.assertNotIn("hunter2secret", res2)
        res3 = extract_tool_display("web_fetch", {"token": "tok-abc", "url": "https://x"})
        self.assertNotIn("tok-abc", res3)

    def test_multiple_tools_many_args(self):
        for name, args in [
            ("read", {"path": "f.py"}),
            ("create", {"TargetFile": "/tmp/a.txt"}),
            ("manage_shell", {"action": "start"}),
            ("unknown", {"query": "x"}),
        ]:
            self.assertIsInstance(extract_tool_display(name, args), str)

    def test_large_nested_dict_args_no_crash(self):
        # Deeply nested values should not crash; name falls back.
        res = extract_tool_display("shell", {"nested": {"a": {"b": {"c": "value"}}}})
        self.assertEqual(res, "shell")
        res2 = extract_tool_display("shell", {"nested": {"a": ["x" * 1000, "y" * 1000]}})
        self.assertIsInstance(res2, str)

    def test_truncate_non_string(self):
        self.assertEqual(truncate(None), "")
        self.assertEqual(truncate(123), "123")
        # NOTE: 0 is falsy so truncate(0) returns "" (minor quirk, unreachable in real use)
        self.assertEqual(truncate(0), "")
        self.assertEqual(truncate(""), "")

    def test_default_tool_name_return_when_no_match(self):
        # numeric value falls through to last-resort numeric pick
        self.assertEqual(extract_tool_display("shell", {"nested": 5}), "5")
        self.assertEqual(extract_tool_display("shell", {"nested": None}), "shell")


if __name__ == "__main__":
    unittest.main()
