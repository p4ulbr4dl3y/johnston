import json
import os
import tempfile
import unittest

from core.audit import append_tool_result
from core.budgets import BudgetLimits, BudgetState


class TestHarnessRuntime(unittest.TestCase):
    def test_budget_blocks_after_tool_call_limit(self):
        budget = BudgetState(BudgetLimits(max_tool_calls=1))

        self.assertTrue(budget.before_tool_call().allowed)
        decision = budget.before_tool_call()

        self.assertFalse(decision.allowed)
        self.assertIn("tool-call budget", decision.reason)

    def test_audit_writes_hash_and_truncated_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                append_tool_result(
                    mode="action",
                    tool="shell",
                    result="token=sk-" + ("a" * 24) + " " + ("x" * 1200),
                    budget={"steps": 1},
                )

                audit_path = os.path.join(".johnston", "audit.jsonl")
                self.assertTrue(os.path.exists(audit_path))
                with open(audit_path, "r", encoding="utf-8") as f:
                    record = json.loads(f.readline())

                self.assertEqual(record["event"], "tool_result")
                self.assertEqual(record["tool"], "shell")
                self.assertEqual(len(record["result_hash"]), 64)
                self.assertIn("[truncated]", record["result_preview"])
                self.assertIn("token=[REDACTED]", record["result_preview"])
                self.assertNotIn("sk-" + ("a" * 24), record["result_preview"])
                self.assertLess(len(record["result_preview"]), 1100)
            finally:
                os.chdir(old_cwd)
