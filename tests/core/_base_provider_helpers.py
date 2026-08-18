"""Shared stream/agent test helpers for the core.base_provider test cluster.

These used to live inside the (now-split) test_base_provider monolith. They are
not collected as tests (no ``test_``/``_test`` suffix).
"""
import asyncio
import unittest.mock

from core.base_provider import BaseAgent


def make_agent(**kwargs):
    """Build a BaseAgent with test defaults, otherwise mirroring the monolith."""
    defaults = dict(api_key="t", model="test-model", base_url="http://t", system_prompt="t", provider_key="tprov")
    defaults.update(kwargs)
    return BaseAgent(**defaults)


class _Chunk:
    """Minimal stream chunk with optional usage/data; no auto-created mock attrs."""

    def __init__(self, choices=None, usage=None, data=None):
        self.choices = choices
        self.usage = usage
        if data is not None:
            self.data = data


class _MockStream:
    """Async iterator stream of chunks that optionally raises after exhausting chunks."""

    def __init__(self, chunks, exc=None):
        self._chunks = list(chunks)
        self._exc = exc

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        if self._exc is not None:
            exc = self._exc
            self._exc = None
            raise exc
        raise StopAsyncIteration


class _BlockingStream(_MockStream):
    """Stream that never terminates after yielding its chunks (for timeouts/cancel)."""

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        await asyncio.sleep(3600)


def _delta(content=None, reasoning_content=None, tool_calls=None):
    d = unittest.mock.MagicMock()
    d.reasoning_content = reasoning_content
    d.reasoning = None
    d.model_extra = None
    d.content = content
    d.tool_calls = tool_calls
    return d


def _text_chunk(text):
    return _Chunk(choices=[unittest.mock.MagicMock(delta=_delta(content=text))])


def _tool_call_chunk(index, tc_id, name, args_json, reasoning=None):
    tc = unittest.mock.MagicMock()
    tc.index = index
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = args_json
    return _Chunk(choices=[unittest.mock.MagicMock(delta=_delta(tool_calls=[tc], reasoning_content=reasoning))])


def _usage_chunk(prompt, completion, total, cached=0):
    usage = unittest.mock.MagicMock()
    usage.prompt_tokens = prompt
    usage.completion_tokens = completion
    usage.total_tokens = total
    usage.prompt_tokens_details = unittest.mock.MagicMock(cached_tokens=cached)
    return _Chunk(choices=[], usage=usage)


class _Attachment:
    def __init__(self, path):
        self.path = path
