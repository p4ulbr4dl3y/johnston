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
        self.assertIn("[plan updated | 1/3 done | Refactoring module for safety]", res.content)
        self.assertIn("Refactoring module for safety", res.content)
        self.assertIn("[plan updated | 1/3 done | Refactoring module for safety]", res.display)

    async def test_update_plan_tool_invalid_payload(self):
        tool = UpdatePlanTool()
        res_empty = str(await tool.execute({"plan": []}))
        self.assertIn("ERR:", res_empty)

        res_malformed = str(await tool.execute({"plan": "not a list"}))
        self.assertIn("ERR:", res_malformed)

    async def test_update_plan_tool_string_list(self):
        tool = UpdatePlanTool()
        args = {
            "plan": [
                "Explore tests and fixtures",
                "Fix provider parsing",
                "Run test suite",
            ]
        }
        res = await tool.execute(args)
        self.assertIn("[plan updated | 0/3 done]", res.content)
        self.assertIn("[plan updated | 0/3 done]", res.display)

    async def test_update_plan_normalization_and_skipping(self):
        tool = UpdatePlanTool()
        args = {
            "plan": [
                12345,  # non-dict, non-str item skipped
                None,  # skipped
                "   ",  # empty string skipped
                "Valid string step",  # str -> pending
                {"step": "   ", "status": "pending"},  # empty step skipped
                {"step": "No status item"},  # missing status -> 'pending'
                {"step": "Unknown status item", "status": "random_status"},  # invalid status -> 'pending'
                {"step": "Completed item", "status": "completed"},
            ]
        }
        res = await tool.execute(args)
        self.assertIn("[plan updated | 1/4 done]", res.content)
        self.assertIn("[plan updated | 1/4 done]", res.display)

    async def test_update_plan_no_valid_items(self):
        tool = UpdatePlanTool()
        res = str(await tool.execute({"plan": [123, None, "", "   ", {"step": ""}]}))
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
        self.assertIn("[plan updated | 0/1 done | App update test]", res.content)
        self.assertIn("[plan updated | 0/1 done | App update test]", res.display)
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
        self.assertIn("[plan updated | 1/1 done]", res.content)
        self.assertIn("[plan updated | 1/1 done]", res.display)

    async def test_update_plan_json_string_payload(self):
        tool = UpdatePlanTool()
        args = {
            "plan": '[{"step": "Step 1", "status": "completed"}, {"step": "Step 2", "status": "in_progress"}]'
        }
        res = await tool.execute(args)
        self.assertIn("[plan updated | 1/2 done]", res.content)

    async def test_update_plan_nested_agent_host_integration(self):
        class MockApp:
            def __init__(self):
                self.updated = False
                self.current_plan = None
                self.current_plan_explanation = None

            def on_plan_update(self, plan, explanation):
                self.updated = True

        class MockAgent:
            def __init__(self, host_app):
                self.app = host_app
                self.current_plan = None
                self.current_plan_explanation = None

        app = MockApp()
        agent = MockAgent(app)
        tool = UpdatePlanTool()
        res = await tool.execute(
            {
                "explanation": "Nested test",
                "plan": [{"step": "Step 1", "status": "completed"}],
            },
            ctx=agent,
        )
        self.assertIn("[plan updated | 1/1 done | Nested test]", res.content)
        self.assertTrue(app.updated)
        self.assertEqual(app.current_plan_explanation, "Nested test")
        self.assertEqual(agent.current_plan_explanation, "Nested test")


if __name__ == "__main__":
    unittest.main()

