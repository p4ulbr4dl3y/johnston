"""Unit tests for the shared stream-step parser (parse_stream_step)."""
import unittest

from core.domain.defaults.errors import parse_stream_step, parse_tool_result_step


class TestParseStreamStep(unittest.TestCase):
    def test_empty_step_returns_none(self):
        self.assertIsNone(parse_stream_step(()))
        self.assertIsNone(parse_stream_step([]))
        self.assertIsNone(parse_stream_step(None))

    def test_thinking_start(self):
        s = parse_stream_step(("thinking_start", "Thinking...", ""))
        self.assertEqual(s.event_type, "thinking_start")
        self.assertEqual(s.val1, "Thinking...")
        self.assertEqual(s.val2, "")
        self.assertIsNone(s.val3)
        self.assertIsNone(s.val4)

    def test_thinking_delta(self):
        s = parse_stream_step(("thinking_delta", "step", ""))
        self.assertEqual(s.event_type, "thinking_delta")
        self.assertEqual(s.val1, "step")

    def test_thinking_end(self):
        s = parse_stream_step(("thinking_end", "1.5", "thoughts"))
        self.assertEqual(s.event_type, "thinking_end")
        self.assertEqual(s.val1, "1.5")
        self.assertEqual(s.val2, "thoughts")

    def test_tool(self):
        s = parse_stream_step(("tool", "shell", "pwd", {"cmd": "pwd"}))
        self.assertEqual(s.event_type, "tool")
        self.assertEqual(s.val1, "shell")
        self.assertEqual(s.val2, "pwd")
        self.assertEqual(s.val3, {"cmd": "pwd"})

    def test_tool_result_common_prefix(self):
        s = parse_stream_step(("tool_result", "ok", "", False, "done", 0))
        self.assertEqual(s.event_type, "tool_result")
        self.assertEqual(s.val1, "ok")
        self.assertEqual(s.val2, "")
        self.assertEqual(s.val3, False)
        self.assertEqual(s.val4, "done")
        # The tool_result-specific tail is parsed by its own helper.
        parsed = parse_tool_result_step(("tool_result", "ok", "", False, "done", 0))
        self.assertEqual(parsed.content, "ok")
        self.assertFalse(parsed.is_error)
        self.assertEqual(parsed.status.value, "done")
        self.assertEqual(parsed.returncode, 0)

    def test_bot_delta(self):
        s = parse_stream_step(("bot_delta", "hello", ""))
        self.assertEqual(s.event_type, "bot_delta")
        self.assertEqual(s.val1, "hello")

    def test_bot_text(self):
        s = parse_stream_step(("bot_text", "final", ""))
        self.assertEqual(s.event_type, "bot_text")
        self.assertEqual(s.val1, "final")

    def test_queued_user_message_full(self):
        s = parse_stream_step(("queued_user_message", "msg", ["a.txt"], True, "/skill"))
        self.assertEqual(s.event_type, "queued_user_message")
        self.assertEqual(s.val1, "msg")
        self.assertEqual(s.val2, ["a.txt"])
        self.assertIs(s.val3, True)
        self.assertEqual(s.val4, "/skill")

    def test_error(self):
        s = parse_stream_step(("error", "boom", ""))
        self.assertEqual(s.event_type, "error")
        self.assertEqual(s.val1, "boom")

    def test_retry(self):
        s = parse_stream_step(("retry", 2, 3, 1.5, ValueError("rate limit")))
        self.assertEqual(s.event_type, "retry")
        self.assertEqual(s.val1, 2)
        self.assertEqual(s.val2, 3)
        self.assertEqual(s.val3, 1.5)
        self.assertIsInstance(s.val4, ValueError)

    def test_short_tuple_falls_back(self):
        s = parse_stream_step(("bot_text",))
        self.assertEqual(s.event_type, "bot_text")
        self.assertEqual(s.val1, "")
        self.assertEqual(s.val2, "")
        self.assertIsNone(s.val3)


if __name__ == "__main__":
    unittest.main()
