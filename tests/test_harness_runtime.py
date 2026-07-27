import json
import os
import tempfile
import unittest

from core.audit import append_tool_result
from core.budgets import BudgetLimits, BudgetState
from core.trace import rollback_last_transaction, summarize_trace


class TestHarnessRuntime(unittest.TestCase):
    def test_budget_blocks_after_tool_call_limit(self):
        budget = BudgetState(BudgetLimits(max_tool_calls=1))

        self.assertTrue(budget.before_tool_call().allowed)
        decision = budget.before_tool_call()

        self.assertFalse(decision.allowed)
        self.assertIn("tool-call budget", decision.reason)

    def test_trace_writes_hash_and_truncated_preview(self):
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
                trace_path = os.path.join(".johnston", "trace.jsonl")
                self.assertTrue(os.path.exists(trace_path))
                with open(trace_path, "r", encoding="utf-8") as f:
                    record = json.loads(f.readline())

                self.assertEqual(record["event"], "tool_result")
                self.assertEqual(record["tool"], "shell")
                self.assertEqual(len(record["result_hash"]), 64)
                self.assertIn("[truncated]", record["result_preview"])
                self.assertIn("token=[REDACTED]", record["result_preview"])
                self.assertNotIn("sk-" + ("a" * 24), record["result_preview"])
                self.assertLess(len(record["result_preview"]), 1100)
                summary = summarize_trace(trace_path)
                self.assertEqual(summary["events"], 1)
                self.assertEqual(summary["tools"], {"shell": 1})
            finally:
                os.chdir(old_cwd)

    def test_rollback_without_checkpoint_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg = rollback_last_transaction(os.path.join(tmp, "missing.jsonl"))

        self.assertFalse(ok)
        self.assertIn("No transaction checkpoint", msg)
