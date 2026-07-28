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
                {"step": "Run pytest suite", "status": "pending"}
            ]
        }
        res = await tool.execute(args)
        self.assertIn("Plan updated (1/3 completed).", res)
        self.assertIn("Refactoring module for safety", res)

    async def test_update_plan_tool_invalid_payload(self):
        tool = UpdatePlanTool()
        res_empty = await tool.execute({"plan": []})
        self.assertIn("Error:", res_empty)

        res_malformed = await tool.execute({"plan": "not a list"})
        self.assertIn("Error:", res_malformed)


if __name__ == "__main__":
    unittest.main()
