import unittest

from core.base_provider import BaseAgent
from core.token_util import estimate_tokens, parse_usage


class DummyUsage:
    def __init__(self, prompt, completion, total):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total

class TestTokenUtil(unittest.TestCase):
    def test_estimate_tokens(self):
        self.assertEqual(estimate_tokens("1234"), 1)
        self.assertEqual(estimate_tokens("12345678"), 2)
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens(None), 0)
        self.assertEqual(estimate_tokens({"key": "val"}), round(len('{"key": "val"}') / 4))

    def test_parse_usage(self):
        usage = DummyUsage(10, 20, 30)
        parsed = parse_usage(usage)
        self.assertEqual(parsed["prompt_tokens"], 10)
        self.assertEqual(parsed["completion_tokens"], 20)
        self.assertEqual(parsed["total_tokens"], 30)

        parsed_none = parse_usage(None)
        self.assertEqual(parsed_none["total_tokens"], 0)

    def test_base_agent_metrics(self):
        agent = BaseAgent("key", "model", "http://localhost", "prompt", [])
        metrics = agent.get_metrics()
        self.assertEqual(metrics["total_tokens"], 0)
        self.assertEqual(metrics["tokens_input"], 0)
        self.assertEqual(metrics["tokens_output"], 0)

        agent.total_tokens = 150
        self.assertEqual(agent.get_metrics()["total_tokens"], 150)

        agent.clear_history()
        self.assertEqual(agent.get_metrics()["total_tokens"], 0)

    def test_models_catalog_context_window(self):
        from core.models_catalog import format_context_tokens, get_context_window
        self.assertEqual(format_context_tokens(128000), "128k")
        self.assertEqual(format_context_tokens(200000), "200k")
        self.assertEqual(format_context_tokens(1000000), "1M")

        ctx = get_context_window("opencode", "deepseek-v4-flash")
        self.assertEqual(ctx, "1M")

        ctx_sonnet = get_context_window("anthropic", "claude-3-5-sonnet")
        self.assertEqual(ctx_sonnet, "200k")

if __name__ == "__main__":
    unittest.main()
