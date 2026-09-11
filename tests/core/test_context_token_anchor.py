"""Tests for the unified API-anchored context-token counter.

The status footer's ``context_used`` and the auto-compaction decision must be
driven by ONE counter — the API-reported ``prompt_tokens`` (anchored in
``BaseAgent._ctx_api_tokens``) plus the heuristic delta since that report —
instead of the heuristic ``estimate_tokens()`` which undercounts
Cyrillic/CJK-heavy sessions (~2-3x).
"""

from unittest.mock import AsyncMock

import pytest

from johnston.core.application.session.rewind import reset_token_counters
from johnston.core.infrastructure.llm.base import BaseAgent
from johnston.core.infrastructure.llm.base.compaction import should_compact


def _agent() -> BaseAgent:
    return BaseAgent(
        api_key="mock",
        model="mock",
        base_url="https://example.com",
        system_prompt="",
        provider_key="mock",
    )


def _anchor_agent(api_tokens: int, api_hist_tokens: int, hist_tokens: int) -> BaseAgent:
    """Agent whose accumulator reports ``hist_tokens`` without a recompute."""
    agent = _agent()
    agent.history = []
    agent._history_tokens = hist_tokens
    agent._history_ident = id(agent.history)
    agent._history_len = 0
    agent._ctx_api_tokens = api_tokens
    agent._ctx_api_hist_tokens = api_hist_tokens
    return agent


def test_get_metrics_returns_anchor_plus_delta():
    agent = _anchor_agent(api_tokens=1000, api_hist_tokens=500, hist_tokens=800)
    assert agent.current_context_tokens() == 1300
    metrics = agent.get_metrics()
    assert metrics["context_used"] == 1300
    # The peek for persistence is refreshed from the same counter.
    assert agent.last_context_tokens == 1300


def test_falls_back_to_heuristic_when_anchor_zero():
    agent = _anchor_agent(api_tokens=0, api_hist_tokens=500, hist_tokens=800)
    agent._last_sys_tokens = 200
    assert agent.current_context_tokens() == 200 + 800
    assert agent.get_metrics()["context_used"] == 200 + 800


def test_accumulate_usage_api_branch_sets_anchor():
    agent = _agent()
    agent._accumulate_usage(
        step_usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    )
    assert agent._ctx_api_tokens == 100
    assert agent._ctx_api_hist_tokens == 0
    assert agent.last_context_tokens == 100


def test_accumulate_usage_heuristic_branch_keeps_anchor():
    agent = _anchor_agent(api_tokens=500, api_hist_tokens=30, hist_tokens=40)
    agent._accumulate_usage(prompt_tokens_est=100, output_tokens_est=50)
    # Heuristic fallback must NOT touch the last real API anchor.
    assert agent._ctx_api_tokens == 500
    assert agent._ctx_api_hist_tokens == 30
    # ... but keeps the legacy peek overwrite behavior as-is.
    assert agent.last_context_tokens == 100


def test_should_compact_divergence_anchor_vs_heuristic():
    """Documenting the divergence: heuristic below threshold, API anchor above."""
    agent = _agent()
    history = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
        {"role": "assistant", "content": "a3"},
    ]
    agent._set_history(history)
    threshold = 1000
    sys_overhead = 100
    # Force a small heuristic history estimate.
    agent._history_tokens = 100
    agent._ctx_api_tokens = 2000
    agent._ctx_api_hist_tokens = 0

    n = len(agent.history)
    assert (
        should_compact(n, sys_overhead, agent._current_history_tokens(), threshold) is False
    ), "pure heuristic (old behavior) would NOT compact"
    assert (
        should_compact(n, 0, agent.current_context_tokens(), threshold) is True
    ), "API-anchored counter MUST compact"


@pytest.mark.asyncio
async def test_compact_messages_if_needed_uses_anchored_value():
    agent = _agent()
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "5"},
        {"role": "assistant", "content": "6"},
    ]
    agent.history = messages[1:]
    # Real API report: anchor huge while the heuristic history estimate is tiny.
    agent._ctx_api_tokens = 6000
    agent._ctx_api_hist_tokens = 0
    agent.compact_history = AsyncMock(return_value=(True, "done"))
    agent.sanitize_history_for_model = lambda h: h

    out, compacted, msg = await agent._compact_messages_if_needed(messages, sys_overhead=0, threshold=1000)
    assert compacted is True
    assert out[0] == {"role": "system", "content": "s"}


@pytest.mark.asyncio
async def test_compact_history_sets_post_compaction_anchor():
    agent = _agent()
    agent.history = [
        {"role": "user", "content": "Fix bug"},
        {"role": "assistant", "content": "Inspecting"},
        {"role": "tool", "tool_call_id": "c", "name": "edit", "content": "ok"},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "Done"},
        {"role": "user", "content": "Submit"},
    ]
    agent._last_sys_tokens = 0
    agent.last_context_tokens = 0

    summary = """\
### Objective
done

### User Decisions & Preferences
(none)

### Constraints
(none)

### State
- Completed: (none)
- Active: (none)
- Pending: (none)
- Blocked: (none)
- Failed approaches: (none)

### Tool Output Anchors
(none)

### Next Steps
1. proceed

### Open Questions
(none)

### Key Files
(none)
"""

    class _FakeAdapter:
        async def stream_chat(self, *a, **k):
            yield ("adapter_text", summary)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("johnston.core.infrastructure.llm.providers.get_adapter", lambda *a, **k: _FakeAdapter())
        success, _msg = await agent.compact_history()
    assert success
    assert agent._ctx_api_tokens == agent.last_context_tokens
    assert agent._ctx_api_tokens > 0
    # current_context_tokens() is anchored at the calibrated compacted size
    # (delta over the post-compaction snapshot is zero).
    assert agent.current_context_tokens() == agent.last_context_tokens


def test_truncate_history_to_user_message_resets_anchor():
    agent = _agent()
    agent.history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "world"},
        {"role": "assistant", "content": "ok"},
    ]
    agent._set_history(agent.history)
    agent._ctx_api_tokens = 4000
    agent._ctx_api_hist_tokens = 100
    agent.truncate_history_to_user_message(1)
    assert agent._ctx_api_tokens == 0
    assert agent._ctx_api_hist_tokens == 0
    # last_context_tokens still holds the recomputed heuristic peek.
    assert agent.last_context_tokens > 0


def test_reset_token_counters_resets_anchor():
    agent = _agent()
    agent._ctx_api_tokens = 4000
    agent._ctx_api_hist_tokens = 100
    reset_token_counters(agent)
    assert agent._ctx_api_tokens == 0
    assert agent._ctx_api_hist_tokens == 0
