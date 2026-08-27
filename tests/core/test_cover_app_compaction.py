"""Coverage-focused unit tests for core/base_provider/compaction.py.

Covers sanitize_history_for_model edge branches, _compact_messages_if_needed
guards and the compact_history adapter/fallback summarizer paths. All provider
streaming is mocked; no real network calls.
"""

import re
import unittest.mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.base_provider import BaseAgent
from core.base_provider.compaction import CompactionMixin
from core.infrastructure.runtime.token_util import estimate_tokens
from core.models_catalog import format_context_tokens


def _agent(history):
    agent = BaseAgent(
        api_key="mock", model="mock", base_url="https://example.com", system_prompt="", provider_key="mock"
    )
    agent.history = history
    return agent


# --- sanitize_history_for_model branches -----------------------------------


def test_sanitize_skips_non_dict_and_invalid_role():
    m = CompactionMixin()
    history = ["not-a-dict", {"role": "bogus", "content": "x"}, {"role": "user", "content": "hi"}]
    out = m.sanitize_history_for_model(history)
    assert out == [{"role": "user", "content": "hi"}]


def test_sanitize_normalizes_tool_call_arguments():
    m = CompactionMixin()
    history = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "a", "function": {"name": "f", "arguments": {"nested": 1}}},
                {"id": "b", "function": {"name": "g", "arguments": "{not valid json"}},
            ],
        }
    ]
    out = m.sanitize_history_for_model(history)
    assert out  # assistant message retained with normalized calls + synthetic tool responses


# --- _compact_messages_if_needed -------------------------------------------


def _min_compactor(compact_result=(True, "msg")):
    obj = CompactionMixin()
    obj.last_context_tokens = 0
    obj.history = []
    obj.compact_history = AsyncMock(return_value=compact_result)
    obj.sanitize_history_for_model = lambda h: h
    return obj


@pytest.mark.asyncio
async def test_compact_if_needed_single_message():
    obj = _min_compactor()
    messages = [{"role": "system", "content": "s"}]
    out, _, _ = await obj._compact_messages_if_needed(messages, sys_overhead=0, threshold=100)
    assert out == messages


@pytest.mark.asyncio
async def test_compact_if_needed_success_branch():
    obj = _min_compactor((True, "done"))
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "5"},
    ]
    history = messages[1:]
    obj.history = history
    obj.sanitize_history_for_model = lambda h: [{"role": "user", "content": "compacted"}]
    out, compacted, msg = await obj._compact_messages_if_needed(messages, sys_overhead=0, threshold=1)
    assert compacted is True
    assert len(out) > 0
    assert out[0] == {"role": "system", "content": "s"}


@pytest.mark.asyncio
async def test_compact_if_needed_failure_branch():
    obj = _min_compactor((False, "tooshort"))
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "5"},
    ]
    out, compacted, msg = await obj._compact_messages_if_needed(messages, sys_overhead=0, threshold=0)
    assert compacted is False
    assert out == messages


@pytest.mark.asyncio
async def test_compact_if_needed_preserves_api_context_when_not_compacting():
    """Regression: a non-compacting tool step must NOT overwrite the API-reported
    context (last_context_tokens) with the heuristic estimate. Previously every
    tool step clobbered the real prompt_tokens with estimate_tokens(), which made
    the footer's context_used oscillate on multilingual sessions (e.g. 65000 ->
    37000) even though no compaction happened."""
    obj = _min_compactor((True, "done"))
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "5"},
        {"role": "assistant", "content": "6", "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c", "content": "ok"},
    ]
    obj.history = messages[1:]
    obj.last_context_tokens = 65000  # real prompt_tokens reported by the API
    # Huge threshold => no compaction is required.
    out, compacted, msg = await obj._compact_messages_if_needed(messages, sys_overhead=0, threshold=10**9)
    assert compacted is False
    assert out == messages
    assert obj.last_context_tokens == 65000  # API value preserved, not clobbered


# --- compact_history summarizer paths --------------------------------------

_SUMMARY = "<objective>done</objective><next_steps>proceed</next_steps>"


@pytest.mark.asyncio
async def test_compact_history_adapter_streaming_success():
    agent = _agent(
        [
            {"role": "user", "content": "Fix bug"},
            {"role": "assistant", "content": "Inspecting"},
            {"role": "tool", "tool_call_id": "c", "name": "edit", "content": "ok"},
            {"role": "user", "content": "more"},
            {"role": "assistant", "content": "Done"},
            {"role": "user", "content": "Submit"},
        ]
    )
    agent._last_sys_tokens = 0
    agent.last_context_tokens = 0

    class _FakeAdapter:
        async def stream_chat(self, *a, **k):
            yield ("adapter_text", _SUMMARY)

    with patch("core.adapters.get_adapter", return_value=_FakeAdapter()):
        success, msg = await agent.compact_history()
    assert any("<conversation_checkpoint>" in m.get("content", "") for m in agent.history)


@pytest.mark.asyncio
async def test_compact_history_report_before_after_same_method():
    """Regression: the compaction report must measure before AND after with the
    SAME estimation method. Previously ``tokens_before`` used a stale
    API-reported ``last_context_tokens`` while ``tokens_after`` used the
    heuristic, so a real (small) reduction showed up as a misleading jump like
    "100M -> 25k" or "65k -> 37k"."""
    history = [
        {"role": "user", "content": "Fix bug"},
        {"role": "assistant", "content": "Inspecting"},
        {"role": "tool", "tool_call_id": "c", "name": "edit", "content": "ok"},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "Done"},
        {"role": "user", "content": "Submit"},
    ]
    agent = _agent(history)
    agent._last_sys_tokens = 0
    # A stale/huge API-reported value must NOT become ``before`` in the report.
    agent.last_context_tokens = 99999999
    sys_tokens = 100
    expected_before = sys_tokens + estimate_tokens(history)

    class _FakeAdapter:
        async def stream_chat(self, *a, **k):
            yield ("adapter_text", _SUMMARY)

    def _fmt(t: int) -> str:
        return f"{t:,}" if t < 10000 else format_context_tokens(t)

    with (
        patch("core.adapters.get_adapter", return_value=_FakeAdapter()),
        patch("core.base_provider.tools.build_prompt_context_async", new_callable=AsyncMock) as mock_bpc,
    ):
        mock_bpc.return_value = ("sys", [], sys_tokens)
        success, msg = await agent.compact_history()
    assert success
    m = re.search(r"\((.+?) → (.+?) tokens\)", msg)
    assert m is not None, msg
    before_fmt, _after_fmt = m.group(1).strip(), m.group(2).strip()
    # before must be derived from the heuristic, NOT the inflated API value.
    assert before_fmt == _fmt(expected_before)
    assert "M" not in before_fmt


@pytest.mark.asyncio
async def test_compact_history_previous_summary_from_tags():
    agent = _agent(
        [
            {"role": "user", "content": "<summary>earlier objective summary</summary>"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
            {"role": "user", "content": "d"},
            {"role": "assistant", "content": "e"},
            {"role": "user", "content": "f"},
            {"role": "assistant", "content": "g"},
            {"role": "user", "content": "h"},
        ]
    )
    agent._last_sys_tokens = 0
    agent.last_context_tokens = 0

    class _FakeAdapter:
        async def stream_chat(self, *a, **k):
            yield ("adapter_text", _SUMMARY)

    with patch("core.adapters.get_adapter", return_value=_FakeAdapter()):
        success, _ = await agent.compact_history()
    assert success


@pytest.mark.asyncio
async def test_compact_history_previous_summary_from_context_note():
    agent = _agent(
        [
            {"role": "user", "content": "[Context Summary of earlier conversation]: the earlier plan"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
            {"role": "user", "content": "d"},
            {"role": "assistant", "content": "e"},
            {"role": "user", "content": "f"},
            {"role": "assistant", "content": "g"},
            {"role": "user", "content": "h"},
        ]
    )
    agent._last_sys_tokens = 0
    agent.last_context_tokens = 0

    class _FakeAdapter:
        async def stream_chat(self, *a, **k):
            yield ("adapter_text", _SUMMARY)

    with patch("core.adapters.get_adapter", return_value=_FakeAdapter()):
        success, _ = await agent.compact_history()
    assert success


@pytest.mark.asyncio
async def test_compact_history_client_fallback_dict_choice():
    agent = _agent(
        [
            {"role": "user", "content": "r1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "r2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "r3"},
        ]
    )
    agent._last_sys_tokens = 0
    agent.last_context_tokens = 0

    class _EmptyAdapter:
        async def stream_chat(self, *a, **k):
            if False:
                yield  # pragma: no cover

    res = {"choices": [{"message": {"content": _SUMMARY}}]}
    with patch("core.adapters.get_adapter", return_value=_EmptyAdapter()):
        with patch.object(agent.client.chat.completions, "create", new_callable=AsyncMock, return_value=res):
            success, _ = await agent.compact_history()
    assert success


@pytest.mark.asyncio
async def test_compact_history_client_fallback_data_choice():
    agent = _agent(
        [
            {"role": "user", "content": "r1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "r2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "r3"},
        ]
    )
    agent._last_sys_tokens = 0
    agent.last_context_tokens = 0

    class _EmptyAdapter:
        async def stream_chat(self, *a, **k):
            if False:
                yield  # pragma: no cover

    res = {"data": {"choices": [{"message": {"content": _SUMMARY}}]}}
    with patch("core.adapters.get_adapter", return_value=_EmptyAdapter()):
        with patch.object(agent.client.chat.completions, "create", new_callable=AsyncMock, return_value=res):
            success, _ = await agent.compact_history()
    assert success


@pytest.mark.asyncio
async def test_compact_history_client_fallback_attr_choice():
    agent = _agent(
        [
            {"role": "user", "content": "r1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "r2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "r3"},
        ]
    )
    agent._last_sys_tokens = 0
    agent.last_context_tokens = 0

    class _EmptyAdapter:
        async def stream_chat(self, *a, **k):
            if False:
                yield  # pragma: no cover

    class _Msg:
        content = _SUMMARY

    class _Obj:
        data = MagicMock(choices=[MagicMock(message=_Msg())])

    with patch("core.adapters.get_adapter", return_value=_EmptyAdapter()):
        with patch.object(agent.client.chat.completions, "create", new_callable=AsyncMock, return_value=_Obj()):
            success, _ = await agent.compact_history()
    assert success


@pytest.mark.asyncio
async def test_compact_history_fallback_error_returns_failure():
    agent = _agent(
        [
            {"role": "user", "content": "r1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "r2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "r3"},
        ]
    )
    agent._last_sys_tokens = 0
    agent.last_context_tokens = 0

    class _EmptyAdapter:
        async def stream_chat(self, *a, **k):
            if False:
                yield  # pragma: no cover

    with patch("core.adapters.get_adapter", return_value=_EmptyAdapter()):
        with patch.object(
            agent.client.chat.completions, "create", new_callable=AsyncMock, side_effect=RuntimeError("boom")
        ):
            success, msg = await agent.compact_history()
    assert success is False
    assert "Failed to generate summary" in msg


@pytest.mark.asyncio
async def test_compact_history_budget_trim_oldest():
    agent = _agent(
        [
            {"role": "user", "content": "r1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "r2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "r3"},
            {"role": "assistant", "content": "a3"},
        ]
    )
    agent._last_sys_tokens = 0
    agent.last_context_tokens = 0

    class _FakeAdapter:
        async def stream_chat(self, *a, **k):
            yield ("adapter_text", _SUMMARY)

    with patch("core.base_provider.compaction.estimate_tokens", return_value=100_000):
        with patch(
            "core.base_provider.BaseAgent.context_limit", new_callable=unittest.mock.PropertyMock
        ) as mock_limit:
            mock_limit.return_value = 1000  # budget = 900 <= 100k -> while loop trims oldest
            with patch("core.adapters.get_adapter", return_value=_FakeAdapter()):
                success, _ = await agent.compact_history()
    assert success


@pytest.mark.asyncio
async def test_compact_history_outer_error_returns_compaction_error():
    agent = _agent(
        [
            {"role": "user", "content": "r1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "r2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "r3"},
        ]
    )
    agent._last_sys_tokens = 0
    agent.last_context_tokens = 0
    # First sanitizer call (pre-summary) succeeds; the in-try call after summary
    # collection raises, exercising the outer "Compaction error" guard.
    calls = {"n": 0}

    def flaky(h):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("sanitize boom")
        return h

    class _FakeAdapter:
        async def stream_chat(self, *a, **k):
            yield ("adapter_text", _SUMMARY)

    with patch.object(agent, "sanitize_history_for_model", side_effect=flaky):
        with patch("core.adapters.get_adapter", return_value=_FakeAdapter()):
            success, msg = await agent.compact_history()
    assert success is False
    assert "Compaction error" in msg
