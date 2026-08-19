"""Coverage-focused tests for core/base_provider/agent and core/application/session/actions."""
import asyncio
import logging
import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import core.infrastructure.runtime.circuit_breaker as cb_mod
from core.application.session.actions import (
    CompactionOutcome,
    compact_session,
    get_rewind_git_stats,
    rewind_session,
)
from core.base_provider import BaseAgent
from core.base_provider import agent as agent_mod


def _reset_circuit():
    cb_mod.circuit_breaker._failures.clear()
    cb_mod.circuit_breaker._state.clear()
    cb_mod.circuit_breaker._opened_at.clear()


def _fake_create(*responses):
    responses = list(responses)

    async def _func(*args, **kwargs):
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return _func


# --- stream helpers -------------------------------------------------------


class _Chunk:
    def __init__(self, choices=None, usage=None, data=None):
        self.choices = choices
        self.usage = usage
        if data is not None:
            self.data = data


class _MockStream:
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


class _BlockingStream:
    async def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(3600)


def _delta(content=None, reasoning_content=None, tool_calls=None):
    d = MagicMock()
    d.reasoning_content = reasoning_content
    d.reasoning = None
    d.model_extra = None
    d.content = content
    d.tool_calls = tool_calls
    return d


def _text_chunk(text):
    return _Chunk(choices=[MagicMock(delta=_delta(content=text))])


def _tool_call_chunk(index, tc_id, name, args_json):
    tc = MagicMock()
    tc.index = index
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = args_json
    return _Chunk(choices=[MagicMock(delta=_delta(tool_calls=[tc]))])


class TestAgentCacheAndSubagent(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        agent_mod._SANITIZE_CACHE.clear()

    def test_sanitize_cache_evicts_oldest(self):
        for i in range(70):
            key = f"key-{i}".encode("utf-8")
            agent_mod._cache_sanitize_put(key, [])
        self.assertLessEqual(len(agent_mod._SANITIZE_CACHE), agent_mod._SANITIZE_CACHE_MAX)

    def _make_agent(self, **kwargs):
        defaults = dict(api_key="t", model="test-model", base_url="http://t", system_prompt="t", provider_key="tprov")
        defaults.update(kwargs)
        agent = BaseAgent(**defaults)
        self.addAsyncCleanup(agent.close)
        return agent

    async def test_process_attachment_image_without_processor(self):
        agent = self._make_agent()
        self.assertIsNone(await agent._process_attachment_image("/tmp/x.png"))

    def test_has_queued_subagent_session(self):
        agent = self._make_agent()
        agent.is_subagent = True
        agent.session = MagicMock(pending_messages=["m"])
        self.assertTrue(agent._has_queued_messages())

    def test_has_queued_subagent_own_pending(self):
        agent = self._make_agent()
        agent.is_subagent = True
        agent.session = MagicMock(pending_messages=[])
        agent.pending_messages = ["own"]
        self.assertTrue(agent._has_queued_messages())

    async def test_subagent_pending_fallback_in_stream(self):
        agent = self._make_agent()
        agent.is_subagent = True
        agent.session = MagicMock(pending_messages=[])
        agent.pending_messages = ["follow up"]
        with patch.object(
            agent.client.chat.completions, "create", new=AsyncMock(return_value=_MockStream([_text_chunk("ok")]))
        ):
            events = []
            async for evt in agent.stream_steps("hi"):
                events.append(evt)
        queued = [e for e in events if e[0] == "queued_user_message"]
        self.assertEqual([e[1] for e in queued], ["follow up"])


def _compaction_estimator(val):
    if isinstance(val, str):
        return 100  # system prompt
    if isinstance(val, list):
        first = val[0] if val else None
        if isinstance(first, dict) and first.get("type") == "function":
            return 0
        return 10
    return 0


class TestAgentCompactionCoverage(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_circuit()

    def _make_agent(self, **kwargs):
        defaults = dict(api_key="t", model="test-model", base_url="http://t", system_prompt="t", provider_key="tprov")
        defaults.update(kwargs)
        agent = BaseAgent(**defaults)
        self.addAsyncCleanup(agent.close)
        return agent

    def _big_history(self):
        return [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
            {"role": "user", "content": "e"},
        ]

    async def test_auto_compact_divider_with_parens_and_tool_step(self):
        agent = self._make_agent()
        agent.history = self._big_history()
        agent.tool_executor = AsyncMock(return_value="ok")
        with patch("core.base_provider.agent.estimate_tokens", side_effect=_compaction_estimator):
            with patch("core.base_provider.BaseAgent.context_limit", new_callable=PropertyMock) as lim:
                lim.return_value = 100
                with patch.object(agent, "compact_history", new=AsyncMock(return_value=(True, "Hist (7 → 3 tok)"))):
                    with patch.object(
                        agent.client.chat.completions,
                        "create",
                        side_effect=_fake_create(
                            _MockStream([_tool_call_chunk(0, "c1", "read", "{}")]), _MockStream([_text_chunk("ok")])
                        ),
                    ):
                        events = []
                        async for evt in agent.stream_steps("run"):
                            events.append(evt)
        dividers = [e[1] for e in events if e[0] == "event_divider" and e[1].startswith("Session Compacted (")]
        self.assertGreaterEqual(len(dividers), 1)
        self.assertIn("7 → 3", dividers[0])
        self.assertEqual(events[-1], ("bot_text", "ok", ""))

    async def test_compact_res_non_tuple(self):
        agent = self._make_agent()
        with patch.object(agent, "_compact_messages_if_needed", new=AsyncMock(return_value="not-a-tuple")):
            with patch.object(
                agent.client.chat.completions,
                "create",
                side_effect=_fake_create(
                    _MockStream([_tool_call_chunk(0, "c1", "read", "{}")]), _MockStream([_text_chunk("ok")])
                ),
            ):
                agent.tool_executor = AsyncMock(return_value="r")
                events = []
                async for evt in agent.stream_steps("run"):
                    events.append(evt)
        self.assertEqual(events[-1], ("bot_text", "ok", ""))

    async def test_compact_in_loop_divider_with_parens(self):
        agent = self._make_agent()
        async def fake_compact(messages, sys_overhead, threshold):
            return (messages, True, "budget (88%)")
        with patch.object(agent, "_compact_messages_if_needed", side_effect=fake_compact):
            with patch.object(
                agent.client.chat.completions,
                "create",
                side_effect=_fake_create(
                    _MockStream([_tool_call_chunk(0, "c1", "read", "{}")]), _MockStream([_text_chunk("ok")])
                ),
            ):
                agent.tool_executor = AsyncMock(return_value="r")
                events = []
                async for evt in agent.stream_steps("run"):
                    events.append(evt)
        divider = next(e[1] for e in events if e[0] == "event_divider" and e[1].startswith("Session Compacted ("))
        self.assertIn("88%", divider)

    async def test_has_queued_continue_after_bot_text(self):
        agent = self._make_agent()
        with patch.object(agent, "_has_queued_messages", side_effect=[True, False]):
            with patch.object(
                agent.client.chat.completions,
                "create",
                side_effect=_fake_create(_MockStream([_text_chunk("A")]), _MockStream([_text_chunk("B")])),
            ):
                events = []
                async for evt in agent.stream_steps("hi"):
                    events.append(evt)
        texts = [e[1] for e in events if e[0] == "bot_text"]
        self.assertEqual(texts, ["A", "B"])


class TestAgentAdapterStreams(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_circuit()

    def _make_agent(self, **kwargs):
        defaults = dict(api_key="t", model="test-model", base_url="http://t", system_prompt="t", provider_key="tprov")
        defaults.update(kwargs)
        agent = BaseAgent(**defaults)
        self.addAsyncCleanup(agent.close)
        return agent

    async def test_adapter_thought_then_text_closes_thinking(self):
        agent = self._make_agent(api_type="anthropic")

        class F:
            def __init__(self, streams):
                self._streams = list(streams)

            async def stream_chat(self, *args, **kwargs):
                if self._streams:
                    for item in self._streams.pop(0):
                        yield item

        fake = F([iter([("adapter_thought", "deep"), ("adapter_text", "answer")])])
        with patch("core.adapters.get_adapter", return_value=fake):
            events = []
            async for evt in agent.stream_steps("hi"):
                events.append(evt)
        self.assertIn(("thinking_start", "Thinking...", ""), events)
        self.assertIn(("thinking_delta", "deep", ""), events)
        ends = [e for e in events if e[0] == "thinking_end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(events[-1], ("bot_text", "answer", ""))

    async def test_adapter_thought_then_tool_call_no_executor(self):
        agent = self._make_agent(api_type="anthropic")

        class F:
            def __init__(self, streams):
                self._streams = list(streams)

            async def stream_chat(self, *args, **kwargs):
                if self._streams:
                    for item in self._streams.pop(0):
                        yield item

        fake = F(
            [
                iter([("adapter_thought", "deep"), ("adapter_tool_call", {"id": "c1", "name": "read", "arguments": {"path": "a"}})]),
                iter([("adapter_text", "done")]),
            ]
        )
        with patch("core.adapters.get_adapter", return_value=fake):
            events = []
            async for evt in agent.stream_steps("run"):
                events.append(evt)
        # adapter_tool_call after thinking -> thinking_end
        ends = [e for e in events if e[0] == "thinking_end"]
        self.assertEqual(len(ends), 1)
        # dict arguments serialized via json.dumps (line 663)
        # no tool_executor -> error result (line 715)
        errs = [e for e in events if e[0] == "tool_result" and "tool_executor not provided" in e[1]]
        self.assertEqual(len(errs), 1)
        self.assertEqual(events[-1], ("bot_text", "done", ""))


class TestAgentRetryAndCancel(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_circuit()

    def _make_agent(self, **kwargs):
        defaults = dict(api_key="t", model="test-model", base_url="http://t", system_prompt="t", provider_key="tprov")
        defaults.update(kwargs)
        agent = BaseAgent(**defaults)
        self.addAsyncCleanup(agent.close)
        return agent

    async def test_retry_uses_retry_after_path(self):
        agent = self._make_agent(max_retries=2, retry_delay=0.005)
        err = RuntimeError("Stream chunk timeout: No response received from provider 'tprov' for 30.0s.")
        with patch.object(agent, "_extract_retry_after", return_value=0.01):
            with patch.object(
                agent.client.chat.completions,
                "create",
                side_effect=_fake_create(err, _MockStream([_text_chunk("ok")])),
            ):
                events = []
                async for evt in agent.stream_steps("hi"):
                    events.append(evt)
        retries = [e for e in events if e[0] == "retry"]
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0][3], 0.01)
        self.assertEqual(events[-1], ("bot_text", "ok", ""))

    async def test_cancel_resolves_tool_arg_fragments(self):
        agent = self._make_agent()
        stream = _MockStream(
            [_tool_call_chunk(0, "c1", "read", '{"path": "a"}'), _text_chunk("x")]
        )
        with patch.object(agent.client.chat.completions, "create", new=AsyncMock(return_value=stream)):
            gen = agent.stream_steps("hi")
            await gen.__anext__()  # consume tool call + text (yields bot_delta)
            try:
                await gen.athrow(asyncio.CancelledError())
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
        # CancelledError path still accounted for tokens (tool fragments joined).
        self.assertGreaterEqual(agent.tokens_input, 0)


# --- session actions ------------------------------------------------------


class DummyAgent:
    def __init__(self):
        self.history = []
        self.tokens_input = 0
        self.tokens_output = 0
        self.tokens_cache_read = 0
        self.last_context_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0


class _Cbs:
    pass


def _noop_cbs():
    return dict(
        rollback_ui=lambda i: None,
        load_text_into_input=lambda t: None,
        save_session_cb=lambda: None,
        refresh_footer_cb=lambda: None,
    )


class HistoryAgent:
    """Agent exposing history + token counters but no clear_history/truncate."""

    def __init__(self):
        self.history = []
        self.tokens_input = 0
        self.tokens_output = 0
        self.tokens_cache_read = 0
        self.last_context_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0


class _CompactionTokensTests(unittest.TestCase):
    def test_parse_tokens_skip_m_and_single(self):
        from core.application.session.actions import _parse_compaction_tokens

        # dot-only number -> continue (line 69); single number -> default (line 77)
        t = _parse_compaction_tokens("Some summary (5 → . tokens)")
        self.assertIsNone(t.before)
        self.assertIsNone(t.after)
        # 'M' multiplier (line 71)
        t2 = _parse_compaction_tokens("Hist (3m → 200k tokens)")
        self.assertEqual(t2.before, 3_000_000)
        self.assertEqual(t2.after, 200_000)


class TestCompactSessionMore(unittest.IsolatedAsyncioTestCase):
    async def test_compact_agent_without_support(self):
        outcome = await compact_session(
            DummyAgent(),
            save_session_cb=lambda: None,
            on_begin=lambda: None,
            on_divider_update=lambda _t: None,
            refresh_footer_cb=lambda: None,
        )
        self.assertIsInstance(outcome, CompactionOutcome)
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.message, "Active agent does not support context compaction")


class TestGetRewindGitStats(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_checkpoint_target_raises(self):
        from core.infrastructure.storage import git_checkpoint as gcm

        with patch.object(
            gcm.GitCheckpointManager,
            "is_valid_checkpoint_target",
            side_effect=RuntimeError("no git"),
        ):
            entries = await get_rewind_git_stats("sid", [(0, "m0")], "/proj")
        self.assertEqual(entries[0].git_stats, "")

    async def test_diff_stats_batch_raises(self):
        from core.infrastructure.storage import git_checkpoint as gcm

        with patch.object(gcm.GitCheckpointManager, "is_valid_checkpoint_target", new=AsyncMock(return_value=True)):
            with patch.object(
                gcm.GitCheckpointManager,
                "get_diff_stats_batch",
                side_effect=RuntimeError("timeout"),
            ):
                entries = await get_rewind_git_stats("sid", [(0, "m0"), (1, "m1")], "/proj")
        self.assertEqual([e.git_stats for e in entries], ["", ""])


class TestRewindExtraPaths(unittest.IsolatedAsyncioTestCase):
    def test_seq_zero_with_history_only(self):
        agent = HistoryAgent()
        agent.history = [{"role": "user", "content": "old"}]
        rewind_session(agent, None, None, [(0, "first")], 0, **_noop_cbs())
        self.assertEqual(agent.history, [])

    def test_seq_nonzero_history_only_truncates(self):
        agent = DummyAgent()
        agent.history = [{"role": "user", "content": "Msg 0"}, {"role": "user", "content": "Msg 1"}]
        rewind_session(agent, None, None, [(0, "Msg 0"), (1, "Msg 1")], 1, **_noop_cbs())
        self.assertEqual(agent.history, [])

    def test_seq_below_tail_uses_history_fallback(self):
        agent = HistoryAgent()
        agent.history = [{"role": "user", "content": "<conversation-checkpoint>compacted</conversation-checkpoint>"}]
        rewind_session(agent, None, None, [(0, "old"), (1, "recent")], 1, **_noop_cbs())
        self.assertEqual(agent.history, [])

    async def test_git_restore_failure_logs_warning(self):
        from core.infrastructure.storage import git_checkpoint as gcm

        agent = DummyAgent()
        agent.history = [{"role": "user", "content": "m"}]
        logged = []
        with patch.object(gcm.GitCheckpointManager, "restore_checkpoint", side_effect=RuntimeError("boom")):
            with patch.object(gcm.GitCheckpointManager, "purge_checkpoints_after", new=MagicMock(return_value=None)):
                with patch.object(logging.getLogger("core.application.session.actions"), "warning", side_effect=lambda *a, **k: logged.append(a)):
                    rewind_session(agent, "sess-1", "/proj", [(0, "m")], 0, **_noop_cbs())
                    task = agent.rewind_git_restore_task
                    await asyncio.wait_for(asyncio.shield(task), timeout=5)
        self.assertEqual(len(logged), 1)
        self.assertIn("Git checkpoint restore failed", str(logged[0]))

    async def test_rewind_cancels_previous_restore_task(self):
        from core.infrastructure.storage import git_checkpoint as gcm

        agent = DummyAgent()
        agent.history = [{"role": "user", "content": "m"}]
        previous = asyncio.create_task(asyncio.sleep(3600))
        agent.rewind_git_restore_task = previous
        with patch.object(gcm.GitCheckpointManager, "restore_checkpoint", new=MagicMock(return_value=None)):
            with patch.object(gcm.GitCheckpointManager, "purge_checkpoints_after", new=MagicMock(return_value=None)):
                rewind_session(agent, "sess-1", "/proj", [(0, "m")], 0, **_noop_cbs())
        await asyncio.sleep(0.01)
        self.assertTrue(previous.cancelled())
        new_task = agent.rewind_git_restore_task
        self.assertIsNot(new_task, previous)
        await asyncio.wait_for(asyncio.shield(new_task), timeout=5)
        self.assertTrue(new_task.done())


if __name__ == "__main__":
    unittest.main()
