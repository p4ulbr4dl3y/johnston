import os
import tempfile
import unittest

from core.harness_eval import default_harness_scenarios, run_harness_scenarios


class TestHarnessEval(unittest.TestCase):
    def test_default_harness_scenarios_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with open("README.md", "w", encoding="utf-8") as f:
                    f.write("test")

                results = run_harness_scenarios(default_harness_scenarios())
                failures = [failure for result in results for failure in result.failures]

                self.assertEqual([], failures)
            finally:
                os.chdir(old_cwd)
