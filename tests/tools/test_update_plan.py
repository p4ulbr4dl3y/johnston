import unittest

from tools.update_plan import UpdatePlanTool


class TestUpdatePlanTool(unittest.IsolatedAsyncioTestCase):
    async def test_update_plan_tool_valid_payload(self):
        tool = UpdatePlanTool()
        args = {
            "explanation": "Refactoring module for safety",
            "plan": [
                {"step": "Analyze requirements", "status": "completed"},
                {"step": "Implement new tool", "status": "in_progress"},
                {"step": "Run pytest suite", "status": "pending"},
            ],
        }
        res = await tool.execute(args)
        self.assertIn("plan updated (1/3 completed)", res)
        self.assertIn("Refactoring module for safety", res)

    async def test_update_plan_tool_invalid_payload(self):
        tool = UpdatePlanTool()
        res_empty = await tool.execute({"plan": []})
        self.assertIn("ERR:", res_empty)

        res_malformed = await tool.execute({"plan": "not a list"})
        self.assertIn("ERR:", res_malformed)

    async def test_update_plan_normalization_and_skipping(self):
        tool = UpdatePlanTool()
        args = {
            "plan": [
                "not a dict item",  # non-dict item skipped
                {"step": "   ", "status": "pending"},  # empty step skipped
                {"text": "Use text fallback", "status": "in_progress"},  # 'text' fallback used
                {"step": "Unknown status item", "status": "random_status"},  # invalid status -> 'pending'
                {"step": "Completed item", "status": "completed"},
            ]
        }
        res = await tool.execute(args)
        self.assertIn("plan updated (1/3 completed)", res)

    async def test_update_plan_no_valid_items(self):
        tool = UpdatePlanTool()
        res = await tool.execute({"plan": ["invalid", {"step": ""}]})
        self.assertIn("ERR: params 'plan': items need", res)

    async def test_update_plan_app_integration(self):
        class MockApp:
            def __init__(self):
                self.updated = False
                self.current_plan = None
                self.current_plan_explanation = None

            def on_plan_update(self, plan, explanation):
                self.updated = True

        app = MockApp()
        tool = UpdatePlanTool()
        res = await tool.execute(
            {
                "explanation": "App update test",
                "plan": [{"step": "Step 1", "status": "in_progress"}],
            },
            ctx=app,
        )
        self.assertIn("plan updated (0/1 completed)", res)
        self.assertTrue(app.updated)
        self.assertEqual(app.current_plan_explanation, "App update test")
        self.assertEqual(app.current_plan, [{"step": "Step 1", "status": "in_progress"}])

    async def test_update_plan_app_callback_exception(self):
        class MockAppFaulty:
            def on_plan_update(self, plan, explanation):
                raise RuntimeError("Callback crash")

        app = MockAppFaulty()
        tool = UpdatePlanTool()
        res = await tool.execute(
            {"plan": [{"step": "Step 1", "status": "completed"}]},
            ctx=app,
        )
        self.assertIn("plan updated (1/1 completed)", res)


if __name__ == "__main__":
    unittest.main()
