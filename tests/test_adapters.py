import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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
                    "function": {"name": "shell", "arguments": '{"command": "ls"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "shell", "content": "file_a\nfile_b"},
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
        self.assertEqual(tu["name"], "shell")
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
        self.assertEqual(fc["functionCall"]["name"], "shell")
        self.assertEqual(fc["functionCall"]["args"], {"command": "ls"})

        resp_turn = contents[2]
        self.assertEqual(resp_turn["role"], "user")
        fr = next(p for p in resp_turn["parts"] if "functionResponse" in p)
        self.assertEqual(fr["functionResponse"]["name"], "shell")

    def test_ollama_normalizes_assistant_tool_call_arguments(self):
        msgs = OllamaAdapter._to_ollama_messages(self._sample_messages())
        assistant = next(m for m in msgs if m["role"] == "assistant" and m.get("tool_calls"))
        tc = assistant["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "shell")
        # arguments converted from JSON string to object
        self.assertEqual(tc["function"]["arguments"], {"command": "ls"})


class _MockUsage:
    def __init__(self, pt, ct, tt):
        self.prompt_tokens = pt
        self.completion_tokens = ct
        self.total_tokens = tt


class _MockDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _MockToolCall:
    def __init__(self, idx, id=None, name=None, arguments=None):
        self.index = idx
        self.id = id
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = arguments


class _MockChoice:
    def __init__(self, delta):
        self.delta = delta


class _MockChunk:
    def __init__(self, choices=None, usage=None):
        self.choices = choices if choices is not None else []
        self.usage = usage


class _MockStreamResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._chunks):
            raise StopAsyncIteration
        c = self._chunks[self._i]
        self._i += 1
        return c


class _MockHttpResponse:
    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _MockStreamCM:
    def __init__(self, lines):
        self._resp = _MockHttpResponse(lines)

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *args):
        pass


class _MockHttpClient:
    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def stream(self, *args, **kwargs):
        return _MockStreamCM(self._lines)


class TestOpenAIAdapterStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_stream_text_and_usage(self):
        chunks = [
            _MockChunk(choices=[_MockChoice(_MockDelta(content="Hello"))]),
            _MockChunk(choices=[_MockChoice(_MockDelta(content=" world"))]),
            _MockChunk(choices=[], usage=_MockUsage(10, 5, 15)),
        ]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_MockStreamResponse(chunks))
        with patch("core.adapters.AsyncOpenAI", return_value=mock_client):
            adapter = OpenAIAdapter()
            events = [e async for e in adapter.stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])]
        texts = [e[1] for e in events if e[0] == "adapter_text"]
        self.assertEqual("".join(texts), "Hello world")
        usage = [e for e in events if e[0] == "adapter_usage"]
        self.assertEqual(usage[0][1]["total_tokens"], 15)

    async def test_stream_tool_call_assembly(self):
        chunks = [
            _MockChunk(choices=[_MockChoice(_MockDelta(tool_calls=[_MockToolCall(0, id="c1", name="shell", arguments='{"com')]))]),
            _MockChunk(choices=[_MockChoice(_MockDelta(tool_calls=[_MockToolCall(0, arguments='mand":"ls"}')]))]),
        ]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_MockStreamResponse(chunks))
        with patch("core.adapters.AsyncOpenAI", return_value=mock_client):
            adapter = OpenAIAdapter()
            events = [e async for e in adapter.stream_chat("http://x", "k", "m", [], tools=[{"type": "function", "function": {"name": "shell"}}])]
        tc = [e for e in events if e[0] == "adapter_tool_call"]
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0][1]["name"], "shell")
        self.assertEqual(tc[0][1]["arguments"], '{"command":"ls"}')

    async def test_stream_max_tokens(self):
        chunks = [_MockChunk(choices=[_MockChoice(_MockDelta(content="x"))])]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_MockStreamResponse(chunks))
        with patch("core.adapters.AsyncOpenAI", return_value=mock_client):
            _ = [e async for e in OpenAIAdapter().stream_chat("http://x", "k", "m", [], max_tokens=100)]
        self.assertEqual(mock_client.chat.completions.create.call_args.kwargs["max_tokens"], 100)


class TestAnthropicAdapterStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_stream_text_and_usage(self):
        lines = [
            'data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}',
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}',
            'data: {"type":"content_block_stop","index":0}',
            'data: {"type":"message_delta","usage":{"output_tokens":5}}',
            'data: {"type":"message_stop"}',
        ]
        with patch("core.adapters.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [e async for e in AnthropicAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])]
        texts = [e[1] for e in events if e[0] == "adapter_text"]
        self.assertEqual("".join(texts), "Hello")
        usage = [e for e in events if e[0] == "adapter_usage"]
        self.assertEqual(usage[0][1]["prompt_tokens"], 10)
        self.assertEqual(usage[0][1]["completion_tokens"], 5)

    async def test_stream_tool_use(self):
        lines = [
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"tu1","name":"shell"}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"cmd\\":"}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"\\"ls\\"}"}}',
            'data: {"type":"content_block_stop","index":0}',
            'data: {"type":"message_stop"}',
        ]
        with patch("core.adapters.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [e async for e in AnthropicAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])]
        tc = [e for e in events if e[0] == "adapter_tool_call"]
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0][1]["name"], "shell")


class TestGeminiAdapterStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_stream_text_and_usage(self):
        lines = [
            'data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}',
            'data: {"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5,"totalTokenCount":15}}',
        ]
        with patch("core.adapters.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])]
        texts = [e[1] for e in events if e[0] == "adapter_text"]
        self.assertEqual("".join(texts), "Hello")
        usage = [e for e in events if e[0] == "adapter_usage"]
        self.assertEqual(usage[0][1]["total_tokens"], 15)

    async def test_stream_function_call(self):
        lines = ['data: {"candidates":[{"content":{"parts":[{"functionCall":{"name":"shell","args":{"command":"ls"}}}]}}]}']
        with patch("core.adapters.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])]
        tc = [e for e in events if e[0] == "adapter_tool_call"]
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0][1]["name"], "shell")


class TestOllamaAdapterStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_stream_text_and_usage(self):
        lines = [
            '{"message":{"content":"Hello"},"done":false}',
            '{"message":{"content":" world"},"done":false}',
            '{"done":true,"prompt_eval_count":10,"eval_count":5}',
        ]
        with patch("core.adapters.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [e async for e in OllamaAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])]
        texts = [e[1] for e in events if e[0] == "adapter_text"]
        self.assertEqual("".join(texts), "Hello world")
        usage = [e for e in events if e[0] == "adapter_usage"]
        self.assertEqual(usage[0][1]["total_tokens"], 15)

    async def test_stream_tool_call(self):
        lines = [
            '{"message":{"content":"","tool_calls":[{"function":{"name":"shell","arguments":{"command":"ls"}}}]},"done":false}',
            '{"done":true,"prompt_eval_count":5,"eval_count":0}',
        ]
        with patch("core.adapters.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [e async for e in OllamaAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])]
        tc = [e for e in events if e[0] == "adapter_tool_call"]
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0][1]["name"], "shell")


class TestAdapterMessageEdgeCases(unittest.TestCase):
    def test_anthropic_empty_messages(self):
        sys_p, msgs = AnthropicAdapter._to_anthropic_messages([])
        self.assertEqual(sys_p, "")
        self.assertEqual(msgs, [])

    def test_anthropic_non_str_system(self):
        sys_p, _ = AnthropicAdapter._to_anthropic_messages([{"role": "system", "content": {"key": "val"}}])
        self.assertIn("key", sys_p)

    def test_anthropic_assistant_list_content(self):
        _, msgs = AnthropicAdapter._to_anthropic_messages([
            {"role": "assistant", "content": [{"type": "text", "text": "P1"}, {"type": "text", "text": "P2"}]}
        ])
        texts = [b["text"] for b in msgs[0]["content"] if b.get("type") == "text"]
        self.assertEqual(len(texts), 2)

    def test_anthropic_no_system(self):
        sys_p, msgs = AnthropicAdapter._to_anthropic_messages([{"role": "user", "content": "hi"}])
        self.assertEqual(sys_p, "")
        self.assertEqual(len(msgs), 1)

    def test_gemini_empty_messages(self):
        sys_instr, contents = GeminiAdapter()._to_gemini([])
        self.assertIsNone(sys_instr)
        self.assertEqual(contents, [])

    def test_gemini_image_data_uri(self):
        msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR="}}]}]
        _, contents = GeminiAdapter()._to_gemini(msgs)
        inline = [p for p in contents[0]["parts"] if "inlineData" in p]
        self.assertEqual(len(inline), 1)
        self.assertEqual(inline[0]["inlineData"]["mimeType"], "image/png")

    def test_gemini_tool_non_dict_content(self):
        _, contents = GeminiAdapter()._to_gemini([{"role": "tool", "name": "shell", "content": 12345}])
        fr = [p for c in contents for p in c["parts"] if "functionResponse" in p]
        self.assertEqual(len(fr), 1)

    def test_ollama_system_role(self):
        msgs = OllamaAdapter._to_ollama_messages([{"role": "system", "content": "Be nice"}, {"role": "user", "content": "hi"}])
        self.assertEqual(msgs[0]["role"], "system")

    def test_ollama_assistant_list_content(self):
        msgs = OllamaAdapter._to_ollama_messages([{"role": "assistant", "content": [{"type": "text", "text": "hello"}]}])
        # Ollama passes content through as-is (truthy values preserved)
        self.assertEqual(msgs[0]["role"], "assistant")
        self.assertEqual(msgs[0]["content"], [{"type": "text", "text": "hello"}])

    def test_ollama_tool_role(self):
        msgs = OllamaAdapter._to_ollama_messages([
            {"role": "user", "content": "do it"},
            {"role": "tool", "tool_call_id": "c1", "content": "result text"},
        ])
        tool_msg = next(m for m in msgs if m["role"] == "tool")
        self.assertEqual(tool_msg["content"], "result text")


class TestAdapterPromptCaching(unittest.IsolatedAsyncioTestCase):
    async def test_anthropic_payload_marks_system_and_tools_for_caching(self):
        captured = {}

        class _CaptureClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def stream(self, *args, **kwargs):
                captured["payload"] = kwargs.get("json")

                class _CM:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                    async def aiter_lines(self):
                        if False:
                            yield ""
                return _CM()

        with patch("core.adapters.httpx.AsyncClient", return_value=_CaptureClient()):
            async for _ in AnthropicAdapter().stream_chat(
                "http://x", "k", "m",
                [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "shell", "parameters": {}}}],
            ):
                pass

        payload = captured["payload"]
        # System is sent as a content block list with an ephemeral cache breakpoint
        self.assertIsInstance(payload["system"], list)
        self.assertEqual(payload["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertIn("You are helpful.", payload["system"][0]["text"])
        # The final tool definition carries a cache breakpoint
        self.assertEqual(payload["tools"][-1]["cache_control"], {"type": "ephemeral"})

    async def test_anthropic_empty_system_not_cached(self):
        captured = {}

        class _CaptureClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def stream(self, *args, **kwargs):
                captured["payload"] = kwargs.get("json")

                class _CM:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                    async def aiter_lines(self):
                        if False:
                            yield ""
                return _CM()

        with patch("core.adapters.httpx.AsyncClient", return_value=_CaptureClient()):
            async for _ in AnthropicAdapter().stream_chat(
                "http://x", "k", "m", [{"role": "user", "content": "hi"}],
            ):
                pass

        # No system prompt -> system stays an empty string, no cache block
        self.assertEqual(captured["payload"]["system"], "")

    async def test_openai_adapter_reports_cached_tokens(self):
        class _UsageWithCache:
            prompt_tokens = 100
            completion_tokens = 10
            total_tokens = 110

            class prompt_tokens_details:
                cached_tokens = 40

        chunks = [_MockChunk(choices=[], usage=_UsageWithCache())]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_MockStreamResponse(chunks))
        with patch("core.adapters.AsyncOpenAI", return_value=mock_client):
            events = [e async for e in OpenAIAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])]
        usage = [e for e in events if e[0] == "adapter_usage"]
        self.assertEqual(usage[0][1]["cache_read_tokens"], 40)
        self.assertEqual(usage[0][1]["prompt_tokens"], 100)


class TestAdapterNormalizationRegression(unittest.TestCase):
    def test_gemini_malformed_tool_arguments_fall_back_to_empty_object(self):
        _, contents = GeminiAdapter()._to_gemini(
            [
                {
                    "role": "assistant",
                    "content": "calling tool",
                    "tool_calls": [{"id": "call_1", "function": {"name": "run", "arguments": "{not json"}}],
                }
            ]
        )

        self.assertEqual(contents[0]["parts"][1]["functionCall"], {"name": "run", "args": {}})

    def test_anthropic_tool_result_without_prior_assistant_is_user_turn(self):
        system_prompt, messages = AnthropicAdapter._to_anthropic_messages(
            [{"role": "tool", "tool_call_id": "call_1", "name": "read", "content": "file contents"}]
        )

        self.assertEqual(system_prompt, "")
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"][0]["tool_use_id"], "call_1")
        self.assertEqual(messages[0]["content"][0]["content"], "file contents")

    def test_ollama_preserves_assistant_multimodal_content(self):
        messages = OllamaAdapter._to_ollama_messages(
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "caption"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                    ],
                }
            ]
        )

        self.assertEqual(messages[0]["role"], "assistant")
        self.assertEqual(messages[0]["content"][0]["text"], "caption")
        self.assertEqual(messages[0]["content"][1]["image_url"]["url"], "data:image/png;base64,abc")


if __name__ == "__main__":
    unittest.main()
