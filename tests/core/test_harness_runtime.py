import unittest

from core.budgets import BudgetLimits, BudgetState


class TestHarnessRuntime(unittest.TestCase):
    def test_budget_blocks_after_tool_call_limit(self):
        budget = BudgetState(BudgetLimits(max_tool_calls=1))

        self.assertTrue(budget.before_tool_call().allowed)
        decision = budget.before_tool_call()

        self.assertFalse(decision.allowed)
        self.assertIn("tool-call budget", decision.reason)
