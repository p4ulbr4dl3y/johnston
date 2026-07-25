import unittest

from core.adapters import AnthropicAdapter, GeminiAdapter, OllamaAdapter, OpenAIAdapter, get_adapter


class TestAdapters(unittest.TestCase):
    def test_get_adapter(self):
        self.assertIsInstance(get_adapter("openai"), OpenAIAdapter)
        self.assertIsInstance(get_adapter("anthropic"), AnthropicAdapter)
        self.assertIsInstance(get_adapter("gemini"), GeminiAdapter)
        self.assertIsInstance(get_adapter("ollama"), OllamaAdapter)
        self.assertIsInstance(get_adapter("unknown"), OpenAIAdapter)


class TestAdapterMessageNormalization(unittest.TestCase):
    """Tool-calling support: native adapters must convert OpenAI-format messages
    (assistant tool_calls + tool results) into their native formats so the agent
    loop can actually execute tools through non-OpenAI providers."""

    def _sample_messages(self):
        return [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "List files."},
            {
                "role": "assistant",
                "content": "Let me check.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"command": "ls"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "bash", "content": "file_a\nfile_b"},
            {"role": "user", "content": "Thanks."},
        ]

    def test_anthropic_normalizes_tool_calls_and_results(self):
        sys_prompt, msgs = AnthropicAdapter._to_anthropic_messages(self._sample_messages())
        self.assertEqual(sys_prompt, "You are helpful.")

        assistant = msgs[1]
        self.assertEqual(assistant["role"], "assistant")
        kinds = [b.get("type") for b in assistant["content"]]
        self.assertIn("text", kinds)
        self.assertIn("tool_use", kinds)
        tu = next(b for b in assistant["content"] if b.get("type") == "tool_use")
        self.assertEqual(tu["name"], "bash")
        self.assertEqual(tu["input"], {"command": "ls"})

        # tool results grouped into a single user turn with tool_result blocks
        tool_msg = msgs[2]
        self.assertEqual(tool_msg["role"], "user")
        tr = next(b for b in tool_msg["content"] if b.get("type") == "tool_result")
        self.assertEqual(tr["tool_use_id"], "call_1")
        self.assertIn("file_a", tr["content"])

    def test_gemini_normalizes_tool_calls_and_results(self):
        sys_instr, contents = GeminiAdapter()._to_gemini(self._sample_messages())
        self.assertEqual(sys_instr["parts"][0]["text"], "You are helpful.")

        model_turn = contents[1]
        self.assertEqual(model_turn["role"], "model")
        fc = next(p for p in model_turn["parts"] if "functionCall" in p)
        self.assertEqual(fc["functionCall"]["name"], "bash")
        self.assertEqual(fc["functionCall"]["args"], {"command": "ls"})

        resp_turn = contents[2]
        self.assertEqual(resp_turn["role"], "user")
        fr = next(p for p in resp_turn["parts"] if "functionResponse" in p)
        self.assertEqual(fr["functionResponse"]["name"], "bash")

    def test_ollama_normalizes_assistant_tool_call_arguments(self):
        msgs = OllamaAdapter._to_ollama_messages(self._sample_messages())
        assistant = next(m for m in msgs if m["role"] == "assistant" and m.get("tool_calls"))
        tc = assistant["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "bash")
        # arguments converted from JSON string to object
        self.assertEqual(tc["function"]["arguments"], {"command": "ls"})


if __name__ == "__main__":
    unittest.main()
