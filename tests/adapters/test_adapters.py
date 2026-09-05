import json
import unittest
from unittest.mock import MagicMock, patch

from core.adapters import (
    AnthropicAdapter,
    GeminiAdapter,
    OpenAIAdapter,
    apply_anthropic_rolling_cache,
    get_adapter,
    sort_keys_recursive,
)


class TestAdapters(unittest.TestCase):
    def test_get_adapter(self):
        self.assertIsInstance(get_adapter("openai"), OpenAIAdapter)
        self.assertIsInstance(get_adapter("anthropic"), AnthropicAdapter)
        self.assertIsInstance(get_adapter("gemini"), GeminiAdapter)
        with self.assertRaises(ValueError):
            get_adapter("unknown")

    def test_sort_keys_recursive(self):
        unsorted = {"z": 1, "a": {"c": 2, "b": 3}, "m": [3, 2, {"y": 4, "x": 5}]}
        sorted_res = sort_keys_recursive(unsorted)
        self.assertEqual(list(sorted_res.keys()), ["a", "m", "z"])
        self.assertEqual(list(sorted_res["a"].keys()), ["b", "c"])
        self.assertEqual(list(sorted_res["m"][2].keys()), ["x", "y"])

    def test_apply_anthropic_rolling_cache(self):
        msgs = [
            {"role": "user", "content": "Hello 1"},
            {"role": "assistant", "content": "Hi 1"},
            {"role": "user", "content": "Hello 2"},
            {"role": "assistant", "content": "Hi 2"},
            {"role": "user", "content": "Hello 3"},
        ]
        apply_anthropic_rolling_cache(msgs)
        # user turn 2 (index 2): rolling anchor breakpoint
        self.assertEqual(
            msgs[2]["content"],
            [{"type": "text", "text": "Hello 2", "cache_control": {"type": "ephemeral"}}],
        )
        # last user turn (index 4): fresh-tail breakpoint (2nd of max 4)
        self.assertEqual(
            msgs[4]["content"],
            [{"type": "text", "text": "Hello 3", "cache_control": {"type": "ephemeral"}}],
        )

    def test_apply_anthropic_rolling_cache_single_user_message(self):
        msgs = [
            {"role": "user", "content": "Only turn"},
            {"role": "assistant", "content": "Hi"},
        ]
        apply_anthropic_rolling_cache(msgs)
        # < 2 user messages: no breakpoints placed at all
        self.assertEqual(msgs[0]["content"], "Only turn")
        self.assertEqual(msgs[1]["content"], "Hi")

    def test_apply_anthropic_rolling_cache_tool_result_tail(self):
        # Realistic tail: tool results arrive as user-role content block lists.
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "List files"}]},
            {"role": "assistant", "content": "checking"},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "a.py\nb.py"},
                    {"type": "tool_result", "tool_use_id": "t2", "content": "big output" * 1000},
                ],
            },
        ]
        apply_anthropic_rolling_cache(msgs)
        content = msgs[2]["content"]
        # Breakpoint lands on the last block; earlier blocks untouched.
        self.assertNotIn("cache_control", content[0])
        self.assertEqual(content[-1]["cache_control"], {"type": "ephemeral"})
        # Clone-on-write: a fresh list is assigned rather than in-place mutation.
        self.assertEqual(len(content), 2)


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

    def test_anthropic_image_tool_result(self):
        import json

        img_json = json.dumps(
            {
                "type": "image",
                "path": "foo.png",
                "media_type": "image/jpeg",
                "base64": "QUFBQQ==",
                "summary": "[Image file: foo.png (100x100)]",
            }
        )
        messages = [
            {"role": "user", "content": "Read img"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_img", "function": {"name": "read", "arguments": '{"path":"foo.png"}'}}],
            },
            {"role": "tool", "tool_call_id": "call_img", "name": "read", "content": img_json},
        ]
        _, final = AnthropicAdapter._to_anthropic_messages(messages)
        user_tool_turn = final[-1]
        tr = next(b for b in user_tool_turn["content"] if b.get("type") == "tool_result")
        self.assertEqual(tr["tool_use_id"], "call_img")
        blocks = tr["content"]
        self.assertEqual(blocks[0]["type"], "text")
        self.assertIn("foo.png", blocks[0]["text"])
        self.assertEqual(blocks[1]["type"], "image")
        self.assertEqual(blocks[1]["source"]["data"], "QUFBQQ==")

    def test_anthropic_user_image_url_conversion(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look at this\n[Image file: 'test.png']"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,QUFB", "detail": "high"},
                    },
                ],
            }
        ]
        _, final = AnthropicAdapter._to_anthropic_messages(messages)
        user_msg = final[0]
        self.assertEqual(user_msg["role"], "user")
        self.assertEqual(user_msg["content"][0], {"type": "text", "text": "Look at this\n[Image file: 'test.png']"})
        self.assertEqual(
            user_msg["content"][1],
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUFB"}},
        )

    def test_gemini_image_tool_result(self):
        import json

        img_json = json.dumps(
            {
                "type": "image",
                "path": "bar.jpg",
                "media_type": "image/jpeg",
                "base64": "QkJCQg==",
                "summary": "[Image file: bar.jpg (200x200)]",
            }
        )
        messages = [
            {"role": "user", "content": "Read img"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_img", "function": {"name": "read", "arguments": '{"path":"bar.jpg"}'}}],
            },
            {"role": "tool", "tool_call_id": "call_img", "name": "read", "content": img_json},
        ]
        _, contents = GeminiAdapter()._to_gemini(messages)
        # Verify functionResponse and inlineData in a single user turn
        resp_turn = contents[2]
        self.assertEqual(resp_turn["role"], "user")
        fr = next(p for p in resp_turn["parts"] if "functionResponse" in p)
        self.assertEqual(fr["functionResponse"]["name"], "read")
        inline_part = next(p for p in resp_turn["parts"] if "inlineData" in p)
        self.assertEqual(inline_part["inlineData"]["data"], "QkJCQg==")

    def test_openai_format_messages_for_image(self):
        import json

        from core.adapters import format_messages_for_openai

        img_json = json.dumps(
            {
                "type": "image",
                "path": "baz.png",
                "media_type": "image/png",
                "base64": "Q0NDQw==",
                "summary": "[Image file: baz.png]",
            }
        )
        messages = [
            {"role": "user", "content": "Read img"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_img", "function": {"name": "read", "arguments": '{"path":"baz.png"}'}}],
            },
            {"role": "tool", "tool_call_id": "call_img", "name": "read", "content": img_json},
        ]
        formatted = format_messages_for_openai(messages)
        tool_msg = formatted[2]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertEqual(tool_msg["content"], "[Image file: baz.png]")

        user_img_msg = formatted[3]
        self.assertEqual(user_img_msg["role"], "user")
        url_part = user_img_msg["content"][1]
        self.assertEqual(url_part["type"], "image_url")
        self.assertIn("data:image/png;base64,Q0NDQw==", url_part["image_url"]["url"])

    def test_openai_parallel_tool_calls_image_sequence(self):
        import json

        from core.adapters import format_messages_for_openai

        img_json = json.dumps(
            {
                "type": "image",
                "path": "img.png",
                "media_type": "image/png",
                "base64": "SU1H",
                "summary": "[Image file: img.png]",
            }
        )
        messages = [
            {"role": "user", "content": "Run 2 tools"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "read", "arguments": '{"path":"img.png"}'}},
                    {"id": "call_2", "function": {"name": "shell", "arguments": '{"command":"ls"}'}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "read", "content": img_json},
            {"role": "tool", "tool_call_id": "call_2", "name": "shell", "content": "file1.txt"},
        ]
        formatted = format_messages_for_openai(messages)
        # Verify tool messages stay contiguous directly after assistant:
        # formatted[0]: user, formatted[1]: assistant, formatted[2]: tool call_1, formatted[3]: tool call_2
        self.assertEqual(formatted[2]["role"], "tool")
        self.assertEqual(formatted[2]["tool_call_id"], "call_1")
        self.assertEqual(formatted[3]["role"], "tool")
        self.assertEqual(formatted[3]["tool_call_id"], "call_2")
        # Injected user image message comes AFTER tool batch (index 4)
        self.assertEqual(formatted[4]["role"], "user")
        self.assertIn("data:image/png;base64,SU1H", formatted[4]["content"][1]["image_url"]["url"])

    def test_openai_reasoning_content_cleared_to_empty_string(self):
        from core.adapters import format_messages_for_openai

        messages = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "thinking output",
                "reasoning_content": "Super long historical thoughts that shouldn't be echoed into context...",
            },
            {
                "role": "assistant",
                "content": "tool call",
                "tool_calls": [{"id": "c1", "function": {"name": "read", "arguments": "{}"}}],
            },
        ]
        formatted = format_messages_for_openai(messages)
        self.assertEqual(formatted[1]["reasoning_content"], "")
        self.assertEqual(formatted[2]["reasoning_content"], "")



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
        lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":" world"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}',
            "data: [DONE]",
        ]
        with patch("core.adapters.openai.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            adapter = OpenAIAdapter()
            events = [e async for e in adapter.stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])]
        texts = [e[1] for e in events if e[0] == "adapter_text"]
        self.assertEqual("".join(texts), "Hello world")
        usage = [e for e in events if e[0] == "adapter_usage"]
        self.assertEqual(usage[0][1]["total_tokens"], 15)

    async def test_stream_tool_call_assembly(self):
        lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"shell","arguments":"{\\"com"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"mand\\":\\"ls\\"}"}}]}}]}',
            "data: [DONE]",
        ]
        with patch("core.adapters.openai.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            adapter = OpenAIAdapter()
            events = [
                e
                async for e in adapter.stream_chat(
                    "http://x", "k", "m", [], tools=[{"type": "function", "function": {"name": "shell"}}]
                )
            ]
        tc = [e for e in events if e[0] == "adapter_tool_call"]
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0][1]["index"], 0)
        self.assertEqual(tc[0][1]["name"], "shell")
        self.assertEqual(tc[0][1]["arguments"], '{"command":"ls"}')
        deltas = [e for e in events if e[0] == "adapter_tool_delta"]
        self.assertGreaterEqual(len(deltas), 2)
        self.assertEqual(deltas[0][1]["name"], "shell")

    async def test_stream_parallel_tool_calls_indices(self):
        lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c0","function":{"name":"read","arguments":""}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"c1","function":{"name":"read","arguments":"{\\"path\\": \\"b.txt\\"}"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"path\\": \\"a.txt\\"}"}}]}}]}',
            "data: [DONE]",
        ]
        with patch("core.adapters.openai.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            adapter = OpenAIAdapter()
            events = [
                e
                async for e in adapter.stream_chat(
                    "http://x", "k", "m", [], tools=[{"type": "function", "function": {"name": "read"}}]
                )
            ]
        calls = [e[1] for e in events if e[0] == "adapter_tool_call"]
        self.assertEqual([c["index"] for c in calls], [0, 1])
        self.assertEqual([c["id"] for c in calls], ["c0", "c1"])
        self.assertEqual(calls[0]["arguments"], '{"path": "a.txt"}')
        self.assertEqual(calls[1]["arguments"], '{"path": "b.txt"}')

    async def test_stream_max_tokens(self):
        lines = ['data: {"choices":[{"delta":{"content":"x"}}]}']
        client = _MockHttpClient(lines)
        with patch("core.adapters.openai.httpx.AsyncClient", return_value=client):
            _ = [e async for e in OpenAIAdapter().stream_chat("http://x", "k", "m", [], max_tokens=100)]
        self.assertIsNotNone(client)


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
        with patch("core.adapters.anthropic.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e
                async for e in AnthropicAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
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
        with patch("core.adapters.anthropic.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e
                async for e in AnthropicAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
        tc = [e for e in events if e[0] == "adapter_tool_call"]
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0][1]["index"], 0)
        self.assertEqual(tc[0][1]["name"], "shell")
        deltas = [e for e in events if e[0] == "adapter_tool_delta"]
        self.assertGreaterEqual(len(deltas), 3)
        self.assertEqual(deltas[0][1]["name"], "shell")

    async def test_stream_parallel_tool_use_out_of_order_stops(self):
        """Parallel tool blocks that stop out of order must still carry their
        block index, so the agent can restore the declared order."""
        lines = [
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"tu0","name":"read"}}',
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu1","name":"read"}}',
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\": \\"b.txt\\"}"}}',
            'data: {"type":"content_block_stop","index":1}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\": \\"a.txt\\"}"}}',
            'data: {"type":"content_block_stop","index":0}',
            'data: {"type":"message_stop"}',
        ]
        with patch("core.adapters.anthropic.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e
                async for e in AnthropicAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
        calls = [e[1] for e in events if e[0] == "adapter_tool_call"]
        # Arrival order is the block-stop order (1 before 0)...
        self.assertEqual([c["index"] for c in calls], [1, 0])
        self.assertEqual([c["id"] for c in calls], ["tu1", "tu0"])
        # ...but each payload preserves its declared index for downstream sorting.
        self.assertEqual(calls[0]["arguments"], '{"path": "b.txt"}')
        self.assertEqual(calls[1]["arguments"], '{"path": "a.txt"}')

    async def test_stream_thinking_delta(self):
        lines = [
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"let me"}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":" think"}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}',
            'data: {"type":"message_stop"}',
        ]
        with patch("core.adapters.anthropic.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e
                async for e in AnthropicAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
        thoughts = "".join(e[1] for e in events if e[0] == "adapter_thought")
        self.assertEqual(thoughts, "let me think")
        texts = "".join(e[1] for e in events if e[0] == "adapter_text")
        self.assertEqual(texts, "Hello")


class TestGeminiAdapterStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_stream_text_and_usage(self):
        lines = [
            'data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}',
            'data: {"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5,"totalTokenCount":15}}',
        ]
        with patch("core.adapters.gemini.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
        texts = [e[1] for e in events if e[0] == "adapter_text"]
        self.assertEqual("".join(texts), "Hello")
        usage = [e for e in events if e[0] == "adapter_usage"]
        self.assertEqual(usage[0][1]["total_tokens"], 15)

    async def test_stream_usage_implicit_cache(self):
        lines = [
            'data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}',
            'data: {"usageMetadata":{"promptTokenCount":100,"candidatesTokenCount":5,'
            '"totalTokenCount":105,"cachedContentTokenCount":80}}',
        ]
        with patch("core.adapters.gemini.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
        usage = [e for e in events if e[0] == "adapter_usage"][0][1]
        self.assertEqual(usage["cache_read_tokens"], 80)
        # prompt_tokens stays the full prompt; uncached is derived downstream.
        self.assertEqual(usage["prompt_tokens"], 100)

    async def test_stream_usage_no_cache_field(self):
        lines = [
            'data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}',
            'data: {"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5,"totalTokenCount":15}}',
        ]
        with patch("core.adapters.gemini.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
        usage = [e for e in events if e[0] == "adapter_usage"][0][1]
        self.assertEqual(usage["cache_read_tokens"], 0)

    async def test_stream_function_call(self):
        lines = [
            'data: {"candidates":[{"content":{"parts":[{"functionCall":{"name":"shell","args":{"command":"ls"}}}]}}]}'
        ]
        with patch("core.adapters.gemini.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
        tc = [e for e in events if e[0] == "adapter_tool_call"]
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0][1]["index"], 0)
        self.assertEqual(tc[0][1]["name"], "shell")

    async def test_stream_thinking(self):
        lines = [
            'data: {"candidates":[{"content":{"parts":[{"thought":"hmm"},{"text":"Hello"}]}}]}',
            'data: {"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5,"totalTokenCount":15}}',
        ]
        with patch("core.adapters.gemini.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
        thoughts = "".join(e[1] for e in events if e[0] == "adapter_thought")
        self.assertEqual(thoughts, "hmm")
        texts = "".join(e[1] for e in events if e[0] == "adapter_text")
        self.assertEqual(texts, "Hello")

    async def test_stream_thinking_non_str_serialized(self):
        lines = ['data: {"candidates":[{"content":{"parts":[{"thought":{"inner":"deep"}}]}}]}']
        with patch("core.adapters.gemini.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
        thoughts = [e[1] for e in events if e[0] == "adapter_thought"]
        self.assertEqual(len(thoughts), 1)
        self.assertIn("deep", thoughts[0])

    async def test_stream_finish_reason(self):
        lines = ['data: {"candidates":[{"content":{"parts":[{"thought":"deep"}]},"finishReason":"MAX_TOKENS"}]}']
        with patch("core.adapters.gemini.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
        reasons = [e[1] for e in events if e[0] == "adapter_finish_reason"]
        self.assertEqual(reasons, ["MAX_TOKENS"])

    async def test_max_output_tokens_thinking_budget_expansion(self):
        mock_client = _MockHttpClient(['data: {"candidates":[{"content":{"parts":[{"text":"hi"}]}}]}'])
        with patch("core.adapters.gemini.httpx.AsyncClient", return_value=mock_client):
            events = [
                e
                async for e in GeminiAdapter().stream_chat(
                    "http://x", "k", "gemini-2.5-flash", [{"role": "user", "content": "hi"}], thinking_effort="high", max_tokens=4096
                )
            ]
        self.assertTrue(any(e[0] == "adapter_text" for e in events))
        # High effort Gemini 2.5 thinking budget is 24576, so effective maxOutputTokens should be >= 24576 + 8192 = 32768
        call_json = mock_client.last_request_json if hasattr(mock_client, "last_request_json") else None
        if call_json:
            self.assertGreaterEqual(call_json.get("generationConfig", {}).get("maxOutputTokens", 0), 32768)


class TestAdapterMessageEdgeCases(unittest.TestCase):
    def test_anthropic_empty_messages(self):
        sys_p, msgs = AnthropicAdapter._to_anthropic_messages([])
        self.assertEqual(sys_p, "")
        self.assertEqual(msgs, [])

    def test_anthropic_non_str_system(self):
        sys_p, _ = AnthropicAdapter._to_anthropic_messages([{"role": "system", "content": {"key": "val"}}])
        self.assertIn("key", sys_p)

    def test_anthropic_assistant_list_content(self):
        _, msgs = AnthropicAdapter._to_anthropic_messages(
            [{"role": "assistant", "content": [{"type": "text", "text": "P1"}, {"type": "text", "text": "P2"}]}]
        )
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

    def test_gemini_tool_non_dict_content(self):
        _, contents = GeminiAdapter()._to_gemini([{"role": "tool", "name": "shell", "content": 12345}])
        fr = [p for c in contents for p in c["parts"] if "functionResponse" in p]
        self.assertEqual(len(fr), 1)


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

        with patch("core.adapters.anthropic.httpx.AsyncClient", return_value=_CaptureClient()):
            async for _ in AnthropicAdapter().stream_chat(
                "http://x",
                "k",
                "m",
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

        with patch("core.adapters.anthropic.httpx.AsyncClient", return_value=_CaptureClient()):
            async for _ in AnthropicAdapter().stream_chat(
                "http://x",
                "k",
                "m",
                [{"role": "user", "content": "hi"}],
            ):
                pass

        # No system prompt -> system stays an empty string, no cache block
        self.assertEqual(captured["payload"]["system"], "")

    async def test_openai_adapter_reports_cached_tokens(self):
        lines = [
            'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":10,"total_tokens":110,"prompt_tokens_details":{"cached_tokens":40}}}',
            "data: [DONE]",
        ]
        with patch("core.adapters.openai.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
            events = [
                e async for e in OpenAIAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])
            ]
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


class TestAdapterClientPooling(unittest.TestCase):
    def test_anthropic_client_pooling_and_close(self):
        adapter = AnthropicAdapter()
        c1 = adapter._get_client("https://api.anthropic.com", "key1")
        c2 = adapter._get_client("https://api.anthropic.com", "key1")
        c3 = adapter._get_client("https://api.anthropic.com", "key2")
        self.assertIs(c1, c2)
        self.assertIsNot(c1, c3)
        adapter.close()
        self.assertEqual(len(adapter._clients), 0)

    def test_gemini_client_pooling_and_close(self):
        adapter = GeminiAdapter()
        c1 = adapter._get_client("https://generativelanguage.googleapis.com", "key1")
        c2 = adapter._get_client("https://generativelanguage.googleapis.com", "key1")
        c3 = adapter._get_client("https://generativelanguage.googleapis.com", "key2")
        self.assertIs(c1, c2)
        self.assertIsNot(c1, c3)
        adapter.close()
        self.assertEqual(len(adapter._clients), 0)

    def test_openai_client_pooling_and_close(self):
        adapter = OpenAIAdapter()
        c1 = adapter._get_client("https://api.openai.com/v1", "key1")
        c2 = adapter._get_client("https://api.openai.com/v1", "key1")
        c3 = adapter._get_client("https://api.openai.com/v1", "key2")
        self.assertIs(c1, c2)
        self.assertIsNot(c1, c3)
        adapter.close()
        self.assertEqual(len(adapter._clients), 0)


class TestGeminiThoughtStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_gemini_thought_streaming_order(self):
        import json
        adapter = GeminiAdapter()

        sse_data = (
            "data: "
            + json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"thought": True, "text": "let me think"},
                                    {"text": "final answer"},
                                ]
                            }
                        }
                    ]
                }
            )
            + "\n\n"
        )

        class FakeStreamResponse:
            def __init__(self, text):
                self.text = text

            async def aiter_lines(self):
                for line in self.text.splitlines():
                    yield line

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class FakeClient:
            def stream(self, *args, **kwargs):
                return FakeStreamResponse(sse_data)

        with patch.object(adapter, "_get_client", return_value=FakeClient()):
            with patch("core.adapters.gemini.check_httpx_response_status", return_value=None):
                events = [e async for e in adapter.stream_chat(base_url="http://test", api_key="k", model="gemini-2.5-flash", messages=[{"role": "user", "content": "hi"}])]

        tags = [e[0] for e in events]
        self.assertIn("adapter_thought", tags)
        self.assertIn("adapter_text", tags)
        thought_events = [e[1] for e in events if e[0] == "adapter_thought"]
        text_events = [e[1] for e in events if e[0] == "adapter_text"]
        self.assertEqual(thought_events, ["let me think"])
        self.assertEqual(text_events, ["final answer"])

    async def test_gemini_stream_chat_multiple_function_calls_increments_index(self):
        adapter = GeminiAdapter()
        line1 = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [
                        {"functionCall": {"name": "read", "args": {"path": "a.txt"}}},
                        {"functionCall": {"name": "read", "args": {"path": "b.txt"}}},
                    ]
                }
            }]
        })
        sse_data = f"data: {line1}\n\n"

        class FakeStreamResponse:
            def __init__(self, text):
                self.text = text

            async def aiter_lines(self):
                for line in self.text.splitlines():
                    yield line

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class FakeClient:
            def stream(self, *args, **kwargs):
                return FakeStreamResponse(sse_data)

        with patch.object(adapter, "_get_client", return_value=FakeClient()):
            with patch("core.adapters.gemini.check_httpx_response_status", return_value=None):
                events = [e async for e in adapter.stream_chat(
                    base_url="http://test", api_key="k", model="gemini-2.5-flash", messages=[]
                )]

        deltas = [e[1] for e in events if e[0] == "adapter_tool_delta"]
        self.assertEqual(len(deltas), 2)
        self.assertEqual(deltas[0]["index"], 0)
        self.assertEqual(deltas[0]["name"], "read")
        self.assertEqual(deltas[1]["index"], 1)
        self.assertEqual(deltas[1]["name"], "read")
        calls = [e[1] for e in events if e[0] == "adapter_tool_call"]
        self.assertEqual(len(calls), 2)

    async def test_gemini_thought_streaming_ignores_empty_or_whitespace_thought(self):
        import json
        adapter = GeminiAdapter()
        sse_data = (
            "data: "
            + json.dumps({
                "candidates": [{
                    "content": {
                        "parts": [
                            {"thought": True, "text": ""},
                            {"thought": True, "text": "   "},
                            {"thought": True},
                            {"text": "answer"},
                        ]
                    }
                }]
            })
            + "\n\n"
        )

        class FakeStreamResponse:
            def __init__(self, text):
                self.text = text

            async def aiter_lines(self):
                for line in self.text.splitlines():
                    yield line

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class FakeClient:
            def stream(self, *args, **kwargs):
                return FakeStreamResponse(sse_data)

        with patch.object(adapter, "_get_client", return_value=FakeClient()):
            with patch("core.adapters.gemini.check_httpx_response_status", return_value=None):
                events = [e async for e in adapter.stream_chat(
                    base_url="http://test", api_key="k", model="gemini-2.5-flash", messages=[]
                )]

        tags = [e[0] for e in events]
        self.assertNotIn("adapter_thought", tags)
        self.assertIn("adapter_text", tags)


if __name__ == "__main__":
    unittest.main()
