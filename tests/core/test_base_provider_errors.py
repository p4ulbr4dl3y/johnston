"""Error/retry tests for core.base_provider (errors area).

Split out of the former test_base_provider monolith: retryable-error detection,
stream retry success/non-retryable failure, vision-error sanitization+retry,
stream timeout/cancel/reset paths, circuit breaker, and tool-execution errors.
"""
import asyncio
import json
import unittest
import unittest.mock

from core.base_provider import BaseAgent
from tests.core._base_provider_helpers import (
    _Attachment,
    _BlockingStream,
    _Chunk,
    _delta,
    _MockStream,
    _text_chunk,
    _tool_call_chunk,
    _usage_chunk,
    make_agent,
)


class TestRetryableErrors(unittest.IsolatedAsyncioTestCase):
    def test_is_retryable_error(self):
        agent = BaseAgent(api_key="t", model="test-model", base_url="http://t", provider_key="tprov")

        # Retryable errors
        self.assertTrue(
            agent._is_retryable_error(
                RuntimeError("Stream chunk timeout: No response received from provider 'test' for 30.0s.")
            )
        )
        self.assertTrue(agent._is_retryable_error(TimeoutError("Connection timed out")))
        self.assertTrue(agent._is_retryable_error(Exception("HTTP 429 Too Many Requests")))
        self.assertTrue(agent._is_retryable_error(Exception("HTTP 502 Bad Gateway")))

        # Non-retryable errors
        self.assertFalse(agent._is_retryable_error(Exception("Invalid API key provided")))
        self.assertFalse(agent._is_retryable_error(Exception("HTTP 401 Unauthorized")))
        self.assertFalse(
            agent._is_retryable_error(Exception("context_length_exceeded: maximum context length is 4096 tokens"))
        )

    async def test_stream_steps_history_updated_on_exception(self):
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        agent.client = unittest.mock.AsyncMock()
        agent.client.chat.completions.create.side_effect = Exception("API connection error")

        steps = []
        async for step in agent.stream_steps("Hello test"):
            steps.append(step)

        # Confirm user prompt is saved into history despite exception
        self.assertEqual(len(agent.history), 1)
        self.assertEqual(agent.history[0]["role"], "user")
        self.assertEqual(agent.history[0]["content"], "Hello test")

    async def test_stream_steps_retry_success(self):
        agent = BaseAgent(
            api_key="t", model="test-model", base_url="http://t", provider_key="tprov", max_retries=3, retry_delay=0.01
        )
        self.addAsyncCleanup(agent.close)

        mock_delta = unittest.mock.MagicMock()
        mock_delta.reasoning_content = None
        mock_delta.reasoning = None
        mock_delta.model_extra = None
        mock_delta.content = "hello after retry"
        mock_delta.tool_calls = None
        mock_choice = unittest.mock.MagicMock()
        mock_choice.delta = mock_delta
        text_chunk = unittest.mock.MagicMock(spec=["choices"])
        text_chunk.choices = [mock_choice]

        async def mock_aiter(*args, **kwargs):
            yield text_chunk

        mock_response = unittest.mock.MagicMock()
        mock_response.__aiter__ = mock_aiter

        attempts = 0

        async def mock_create(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("Stream chunk timeout: No response received from provider 'tprov' for 30.0s.")
            return mock_response

        with unittest.mock.patch.object(agent.client.chat.completions, "create", side_effect=mock_create):
            events = []
            async for evt in agent.stream_steps("test"):
                events.append(evt)

        self.assertEqual(attempts, 2)
        # Verify retry notice was yielded
        retry_events = [e for e in events if e[0] == "retry"]
        self.assertEqual(len(retry_events), 1)
        self.assertEqual(retry_events[0][1], 1)
        self.assertEqual(retry_events[0][2], 3)
        # Verify bot_text event
        bot_texts = [e for e in events if e[0] == "bot_text"]
        self.assertTrue(any("hello after retry" in e[1] for e in bot_texts))

    async def test_stream_steps_non_retryable_fails_immediately(self):
        agent = BaseAgent(
            api_key="t", model="test-model", base_url="http://t", provider_key="tprov", max_retries=3, retry_delay=0.01
        )
        self.addAsyncCleanup(agent.close)

        attempts = 0

        async def mock_create(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            raise Exception("Invalid API key provided")

        with unittest.mock.patch.object(agent.client.chat.completions, "create", side_effect=mock_create):
            events = []
            async for evt in agent.stream_steps("test"):
                events.append(evt)

        self.assertEqual(attempts, 1)
        api_errors = [e for e in events if e[0] == "event_divider" and "API Error" in e[1]]
        self.assertEqual(len(api_errors), 1)
        self.assertIn("Invalid API key", api_errors[0][1])

    def test_vision_error_sanitization_and_hint(self):
        agent = BaseAgent(api_key="t", model="non-vision-model", base_url="http://t", provider_key="tprov")
        self.addAsyncCleanup(agent.close)

        err = Exception("No endpoints found that support image input")
        self.assertTrue(agent._is_vision_error(err))

        messages = [
            {"role": "user", "content": "Look at image"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "read", "arguments": '{"path":"1.png"}'}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": '{"type": "image", "path": "1.png", "base64": "QUFB"}'},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Preview:"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUFB"}},
                ],
            },
        ]

        sanitized = agent._sanitize_vision_error_messages(messages)
        # Verify user message is preserved with text and note
        self.assertEqual(len(sanitized), 4)
        user_msg = sanitized[3]
        self.assertEqual(user_msg["role"], "user")
        self.assertIn("Preview:", user_msg["content"])
        self.assertIn('<system_note type="warning">', user_msg["content"])
        # Verify tool content was replaced with hint
        tool_msg = sanitized[2]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertIn("ERR: vision_unsupported", tool_msg["content"])

    async def test_stream_cancelled_error_records_tokens(self):
        agent = BaseAgent(api_key="t", model="m", base_url="http://t", provider_key="tprov")
        self.addAsyncCleanup(agent.close)

        chunk = unittest.mock.MagicMock()
        chunk.usage = None
        choice = unittest.mock.MagicMock()
        delta = unittest.mock.NonCallableMagicMock(
            spec=["content", "tool_calls", "reasoning_content", "reasoning", "model_extra"]
        )
        delta.content = "hi"
        delta.tool_calls = None
        delta.reasoning_content = None
        delta.reasoning = None
        delta.model_extra = {}
        choice.delta = delta
        chunk.choices = [choice]

        async def slow_iter():
            yield chunk
            while True:
                await asyncio.sleep(0.01)

        class MockAsyncStream:
            def __aiter__(self):
                return slow_iter()

        with unittest.mock.patch.object(
            agent.client.chat.completions,
            "create",
            new_callable=unittest.mock.AsyncMock,
            return_value=MockAsyncStream(),
        ):
            gen = agent.stream_steps("Hello cancelled")
            await gen.__anext__()
            try:
                await gen.athrow(asyncio.CancelledError())
            except (asyncio.CancelledError, StopAsyncIteration):
                pass

        self.assertGreater(agent.tokens_input, 0)
        self.assertGreaterEqual(agent.total_tokens, agent.tokens_input)


class TestErrorStreamEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Stream error/retry/cancellation paths from the stream_steps loop."""

    def _make_agent(self, **kwargs):
        agent = make_agent(**kwargs)
        self.addAsyncCleanup(agent.close)
        return agent

    async def test_circuit_breaker_open_raises_error(self):
        agent = self._make_agent()
        fake_cb = unittest.mock.MagicMock()
        fake_cb.allow_request.return_value = False
        fake_cb.remaining_cooldown.return_value = 42.0
        with unittest.mock.patch("core.infrastructure.runtime.circuit_breaker.circuit_breaker", fake_cb):
            events = []
            async for evt in agent.stream_steps("hi"):
                events.append(evt)

        fake_cb.allow_request.assert_called_once_with("tprov")
        self.assertEqual(events[-1][0], "event_divider")
        self.assertIn("Circuit breaker for provider 'tprov' is OPEN", events[-1][1])

    async def test_create_retry_without_stream_options_and_reasoning_effort(self):
        agent = self._make_agent(reasoning_effort="high")
        response = _MockStream([_text_chunk("ok")])
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.side_effect = [TypeError("got an unexpected keyword argument 'reasoning_effort'"), response]
            events = []
            async for evt in agent.stream_steps("hi"):
                events.append(evt)

        self.assertEqual(events[-1], ("bot_text", "ok", ""))
        self.assertEqual(mock_create.call_count, 2)
        first_kwargs = mock_create.call_args_list[0].kwargs
        second_kwargs = mock_create.call_args_list[1].kwargs
        self.assertIn("reasoning_effort", first_kwargs)
        self.assertNotIn("reasoning_effort", second_kwargs)
        self.assertNotIn("stream_options", second_kwargs)

    async def test_stream_chunk_timeout_raises_runtime_error(self):
        agent = self._make_agent(chunk_timeout=0.05, max_retries=1)
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = _BlockingStream([])
            events = []
            async for evt in agent.stream_steps("hi"):
                events.append(evt)

        self.assertEqual(events[-1][0], "event_divider")
        self.assertIn("Stream chunk timeout", events[-1][1])
        self.assertIn("tprov", events[-1][1])

    async def test_cancelled_with_usage_records_tokens_and_cost(self):
        from core.models_catalog import catalog

        agent = self._make_agent()
        pricing = {"prompt": 0.01, "completion": 0.03}
        chunks = [_usage_chunk(100, 20, 120, cached=80), _text_chunk("hi")]
        with unittest.mock.patch.object(catalog, "get_model_pricing", return_value=pricing):
            with unittest.mock.patch.object(
                agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
            ) as mock_create:
                mock_create.return_value = _BlockingStream(chunks)
                gen = agent.stream_steps("hi")
                await gen.__anext__()
                try:
                    await gen.athrow(asyncio.CancelledError())
                except (asyncio.CancelledError, StopAsyncIteration):
                    pass

        self.assertEqual(agent.tokens_input, 100)
        self.assertEqual(agent.tokens_output, 20)
        self.assertEqual(agent.tokens_cache_read, 80)
        self.assertEqual(agent.last_context_tokens, 100)
        # uncached_in=20, cached=80 at 0.5x, out=20: 0.2 + 0.4 + 0.6
        self.assertAlmostEqual(agent.cost_usd, 1.2, places=6)

    async def test_vision_error_sanitizes_and_retries(self):
        agent = self._make_agent()
        img_json = json.dumps({"base64": "QUFB", "media_type": "image/png"})
        agent.image_processor = lambda path: img_json
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.side_effect = [
                Exception("No endpoints found that support image input"),
                _MockStream([_text_chunk("ok")]),
            ]
            events = []
            async for evt in agent.stream_steps("Look", attachments=[_Attachment("a.png")]):
                events.append(evt)

        self.assertEqual(mock_create.call_count, 2)
        hints = [e for e in events if e[0] == "thinking" and "does not support vision" in e[1]]
        self.assertEqual(len(hints), 1)
        self.assertEqual(events[-1], ("bot_text", "ok", ""))

    async def test_retry_with_partial_text_yields_blank_delta(self):
        agent = self._make_agent(max_retries=2, retry_delay=0.01)
        timeout_err = RuntimeError("Stream chunk timeout: No response received from provider 'tprov' for 30.0s.")
        first = _MockStream([_text_chunk("partial")], exc=timeout_err)
        second = _MockStream([_text_chunk("done")])
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.side_effect = [first, second]
            events = []
            async for evt in agent.stream_steps("test"):
                events.append(evt)

        self.assertIn(("bot_reset", "", ""), events)
        retry_events = [e for e in events if e[0] == "retry"]
        self.assertEqual(len(retry_events), 1)
        self.assertEqual(events[-1], ("bot_text", "done", ""))

    async def test_tool_execution_error_returns_err_result(self):
        agent = self._make_agent()
        first = _MockStream([_tool_call_chunk(0, "tc_1", "read", '{"path": "a.txt"}')])
        second = _MockStream([_text_chunk("ok")])
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.side_effect = [first, second]
            agent.tool_executor = unittest.mock.AsyncMock()
            agent.tool_executor.side_effect = Exception("boom")
            events = []
            async for evt in agent.stream_steps("read it"):
                events.append(evt)

        err_results = [e for e in events if e[0] == "tool_result" and "ERR: execute 'read': boom" in e[1]]
        self.assertEqual(len(err_results), 1)
        self.assertEqual(events[-1], ("bot_text", "ok", ""))

    async def test_stream_interrupted_by_native_finish_reason_network_error_retries(self):
        agent = self._make_agent(max_retries=2, retry_delay=0.01)
        # First attempt returns empty content with native_finish_reason="network_error"
        err_choice = unittest.mock.MagicMock(
            delta=_delta(content=""),
            finish_reason="stop",
            native_finish_reason="network_error",
        )
        first = _MockStream([_Chunk(choices=[err_choice])])
        second = _MockStream([_text_chunk("recovered")])
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.side_effect = [first, second]
            events = []
            async for evt in agent.stream_steps("test"):
                events.append(evt)

        retry_events = [e for e in events if e[0] == "retry"]
        self.assertEqual(len(retry_events), 1)
        self.assertEqual(events[-1], ("bot_text", "recovered", ""))

