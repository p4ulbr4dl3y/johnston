"""Coverage-focused unit tests for the Gemini / OpenAI adapters.

Covers client-pool close() edge paths, message/content normalisation branches
and streaming error/skip lines that tests/adapters/test_adapters.py misses.
All HTTP is mocked; no real network calls.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.adapters import (
    GeminiAdapter,
    OpenAIAdapter,
    format_messages_for_openai,
)

# --- shared http helpers ----------------------------------------------------


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


class _MockUsage:
    def __init__(self, pt, ct, tt):
        self.prompt_tokens = pt
        self.completion_tokens = ct
        self.total_tokens = tt


class _MockDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


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


# --- Gemini -----------------------------------------------------------------


def test_gemini_close_no_clients():
    adapter = GeminiAdapter()
    adapter._clients = {}
    adapter.close()
    assert adapter._clients == {}


@pytest.mark.asyncio
async def test_gemini_close_with_running_loop_swallowed():
    adapter = GeminiAdapter()
    adapter._clients = {("u", "k"): MagicMock()}
    # asyncio.run() inside a running loop raises RuntimeError -> swallowed.
    adapter.close()
    assert adapter._clients == {}


@pytest.mark.asyncio
async def test_gemini_close_all_aclose_error():
    client = MagicMock()
    client.aclose = AsyncMock(side_effect=RuntimeError("close fail"))
    await GeminiAdapter._close_all({"k": client})  # must not raise


def test_gemini_content_to_parts_list_branches():
    adapter = GeminiAdapter()
    content = [
        {"type": "text", "text": "hello"},
        "not-a-dict-part",
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUFB"}},
        {"type": "image_url", "image_url": {"url": "https://example.com/x.png"}},  # not data: -> skipped
    ]
    parts = adapter._content_to_parts(content, {}, "user")
    texts = [p["text"] for p in parts if "text" in p]
    assert "hello" in texts
    inline = next(p for p in parts if "inlineData" in p)
    assert inline["inlineData"]["mimeType"] == "image/png"
    assert inline["inlineData"]["data"] == "QUFB"


@pytest.mark.asyncio
async def test_gemini_stream_system_tools_skip_lines():
    lines = [
        "",
        'data: {"candidates":[{"content":{"parts":["not-a-dict"]}}]}',
        'data: {"candidates":[{"content":{"parts":[{"text":"hi there"}]}}]}',
    ]
    tools = [
        {"type": "function", "function": {"name": "shell", "description": "run", "parameters": {}}},
        {"type": "function", "function": {}},  # empty function -> skipped declaration
    ]
    messages = [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "hi"}]
    with patch("core.adapters.gemini.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
        events = [
            e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", messages, tools=tools)
        ]
    texts = "".join(e[1] for e in events if e[0] == "adapter_text")
    assert texts == "hi there"


@pytest.mark.asyncio
async def test_gemini_stream_thinking_config_truthy():
    lines = ['data: {"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}']
    with patch("core.adapters.gemini.httpx.AsyncClient", return_value=_MockHttpClient(lines)):
        with patch("core.adapters.gemini.build_gemini_thinking_config", return_value={"thinkingBudget": 2}):
            events = [e async for e in GeminiAdapter().stream_chat("http://x", "k", "m", [], thinking_effort="high")]
    assert any(e[0] == "adapter_text" for e in events)


# --- OpenAI -----------------------------------------------------------------


def test_openai_format_non_dict_message():
    out = format_messages_for_openai(["not-a-dict", {"role": "user", "content": "hi"}])
    assert out[0] == "not-a-dict"


def test_openai_format_tool_call_argument_normalisation():
    messages = [
        {
            "role": "assistant",
            "content": "run",
            "tool_calls": [
                {"id": "a", "function": {"name": "f", "arguments": {"x": 1}}},
                {"id": "b", "function": {"name": "g", "arguments": "{bad json"}},
                "not-a-dict-toolcall",
            ],
        }
    ]
    out = format_messages_for_openai(messages)
    cleaned = out[0]
    calls = cleaned["tool_calls"]
    assert calls[0]["function"]["arguments"] == '{"x": 1}'
    assert calls[1]["function"]["arguments"] == "{}"
    assert calls[2] == "not-a-dict-toolcall"


@pytest.mark.asyncio
async def test_openai_close_no_clients():
    adapter = OpenAIAdapter()
    adapter._clients = {}
    adapter.close()
    assert adapter._clients == {}


@pytest.mark.asyncio
async def test_openai_close_with_running_loop_swallowed():
    adapter = OpenAIAdapter()
    adapter._clients = {("u", "k"): MagicMock()}
    adapter.close()
    assert adapter._clients == {}


@pytest.mark.asyncio
async def test_openai_close_all_error_swallowed():
    client = MagicMock()
    client.close = AsyncMock(side_effect=RuntimeError("close fail"))
    await OpenAIAdapter._close_all({"k": client})  # must not raise


@pytest.mark.asyncio
async def test_openai_stream_data_choices_and_empty_delta():
    mock_client = MagicMock()

    class _DataChunk:
        choices = []
        usage = None
        data = {"choices": [_MockChoice(_MockDelta(content="hello"))]}

    usage_chunk = _MockChunk(choices=[], usage=_MockUsage(5, 2, 7))
    empty_delta_chunk = _MockChunk(choices=[_MockChoice(delta=None)])
    chunks = [usage_chunk, _DataChunk(), empty_delta_chunk]
    mock_client.chat.completions.create = AsyncMock(return_value=_MockStreamResponse(chunks))
    with patch("core.adapters.openai.AsyncOpenAI", return_value=mock_client):
        events = [e async for e in OpenAIAdapter().stream_chat("http://x", "k", "m", [{"role": "user", "content": "hi"}])]
    texts = "".join(e[1] for e in events if e[0] == "adapter_text")
    assert texts == "hello"

