"""Agent tests for core.base_provider (agent area).

Split out of the former test_base_provider monolith: agent cost/token/max-token
properties, history sanitization, stream_steps behavior (tool loops, thinking,
attachments, adapters, subagent drain), and agent-level stream edge cases.
"""
import json
import os
import unittest
import unittest.mock

from core.base_provider import BaseAgent
from tests.conftest import _make_app_mock
from tests.core._base_provider_helpers import (
    _Attachment,
    _Chunk,
    _delta,
    _MockStream,
    _text_chunk,
    _tool_call_chunk,
    make_agent,
)


class TestBaseAgent(unittest.IsolatedAsyncioTestCase):
    def test_agent_cost_usd_calculation(self):
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        self.assertEqual(agent.cost_usd, 0.0)
        metrics = agent.get_metrics()
        self.assertEqual(metrics["cost_usd"], 0.0)

        agent.cost_usd = 0.0025
        self.assertEqual(agent.get_metrics()["cost_usd"], 0.0025)

        agent.clear_history()
        self.assertEqual(agent.cost_usd, 0.0)

    def test_clear_history_resets_sys_tokens_for_new_session(self):
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        # Simulate a prior session having streamed once, caching sys+tools tokens.
        agent._last_sys_tokens = 3100
        agent.history = [{"role": "user", "content": "old session"}]
        agent.last_context_tokens = 0

        # Before /new, metrics reflect the stale sys+tools overhead (non-zero).
        self.assertGreater(agent.get_metrics()["context_used"], 0)

        # /new clears history but must not leak the previous session's overhead.
        agent.clear_history()
        metrics = agent.get_metrics()
        self.assertEqual(metrics["context_used"], 0)
        self.assertEqual(agent._last_sys_tokens, 0)

    def test_default_max_tokens_is_8192(self):
        agent = BaseAgent(api_key="t", model="m", base_url="http://t", system_prompt="t", provider_key="p")
        self.addAsyncCleanup(agent.close)
        # Raised from 4096 so long code answers are not truncated mid-generation.
        self.assertEqual(agent.max_tokens, 8192)

    async def test_sanitize_history_for_model(self):
        agent = BaseAgent(api_key="test", model="non-vision-model", base_url="http://test", provider_key="opencode")
        self.addAsyncCleanup(agent.close)

        history = [
            {"role": "user", "content": "Look at this"},
            {"role": "assistant", "content": "Done", "tool_calls": [{"id": "call_1", "function": {"name": "read"}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "read", "content": "file contents"},
            {"role": "tool", "tool_call_id": "call_orphan", "name": "edit", "content": "orphan content"},
        ]

        sanitized = agent.sanitize_history_for_model(history)
        self.assertEqual(len(sanitized), 4)

        # Valid tool output preserved
        self.assertEqual(sanitized[2]["role"], "tool")
        self.assertEqual(sanitized[2]["tool_call_id"], "call_1")

        # Orphan tool converted to user role
        self.assertEqual(sanitized[3]["role"], "user")
        self.assertIn("orphan content", sanitized[3]["content"])

    async def test_sanitize_history_interrupted_tool_calls(self):
        agent = BaseAgent(api_key="test", model="non-vision-model", base_url="http://test", provider_key="opencode")
        self.addAsyncCleanup(agent.close)

        history = [
            {"role": "user", "content": "Run tools"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "read"}},
                    {"id": "call_2", "function": {"name": "shell"}},
                ],
            },
            {"role": "user", "content": "Next question"},
        ]

        sanitized = agent.sanitize_history_for_model(history)
        # Should inject 2 synthetic tool responses for call_1 and call_2 before the User message
        self.assertEqual(len(sanitized), 5)
        self.assertEqual(sanitized[0]["role"], "user")
        self.assertEqual(sanitized[1]["role"], "assistant")
        self.assertEqual(sanitized[2]["role"], "tool")
        self.assertEqual(sanitized[2]["tool_call_id"], "call_1")
        self.assertIn("interrupted or cancelled", sanitized[2]["content"])
        self.assertEqual(sanitized[3]["role"], "tool")
        self.assertEqual(sanitized[3]["tool_call_id"], "call_2")
        self.assertIn("interrupted or cancelled", sanitized[3]["content"])
        self.assertEqual(sanitized[4]["role"], "user")
        self.assertEqual(sanitized[4]["content"], "Next question")

    async def test_sanitize_history_drops_empty_user_content(self):
        agent = BaseAgent(api_key="test", model="non-vision-model", base_url="http://test", provider_key="opencode")
        self.addAsyncCleanup(agent.close)

        history = [
            {"role": "user", "content": "Look at this"},
            {"role": "assistant", "content": "Done"},
            {"role": "user", "content": ""},
            {"role": "user", "content": "   "},
            {"role": "user", "content": None},
            {"role": "user", "content": "Valid question"},
        ]

        sanitized = agent.sanitize_history_for_model(history)
        # Empty/whitespace/None user messages are dropped to avoid the OpenAI
        # 400 "user message must have content" error; non-empty messages survive.
        roles_contents = [(m["role"], m["content"]) for m in sanitized]
        self.assertEqual(
            roles_contents,
            [
                ("user", "Look at this"),
                ("assistant", "Done"),
                ("user", "Valid question"),
            ],
        )

    async def test_stream_steps_without_chunk_usage(self):
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        self.addAsyncCleanup(agent.close)

        mock_chunk = unittest.mock.MagicMock(spec=["choices"])
        mock_delta = unittest.mock.MagicMock()
        mock_delta.reasoning_content = None
        mock_delta.reasoning = None
        mock_delta.model_extra = None
        mock_delta.content = "Hello world"
        mock_delta.tool_calls = None
        mock_choice = unittest.mock.MagicMock()
        mock_choice.delta = mock_delta
        mock_chunk.choices = [mock_choice]

        async def mock_aiter(*args, **kwargs):
            yield mock_chunk

        mock_response = unittest.mock.MagicMock()
        mock_response.__aiter__ = mock_aiter

        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response

            steps = []
            async for step in agent.stream_steps("Hi"):
                steps.append(step)

            self.assertTrue(len(steps) > 0)
            self.assertIn(("bot_delta", "Hello world", ""), steps)
            self.assertEqual(steps[-1], ("bot_text", "Hello world", ""))
            self.assertGreater(agent.tokens_input, 0)
            self.assertGreater(agent.tokens_output, 0)

    async def test_cost_usd_cache_multiplier_anthropic_vs_openai(self):
        # Cached input is discounted ~90% for Anthropic (0.1x) and ~50% for
        # OpenAI-compatible (0.5x). The same cached usage event must therefore
        # produce a lower cost for an Anthropic-type agent than an OpenAI-type one.
        from unittest.mock import patch

        from core.models_catalog import catalog

        cached_usage = {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "cache_read_tokens": 80,
        }

        # OpenAI path: the agent talks to self.client directly and parses usage
        # off each streamed chunk.
        mock_delta = unittest.mock.MagicMock()
        mock_delta.reasoning_content = None
        mock_delta.reasoning = None
        mock_delta.model_extra = None
        mock_delta.content = None
        mock_delta.tool_calls = None
        mock_choice = unittest.mock.MagicMock()
        mock_choice.delta = mock_delta
        usage_chunk = unittest.mock.MagicMock(spec=["choices", "usage"])
        usage_chunk.choices = []
        usage_chunk.usage = unittest.mock.MagicMock(prompt_tokens=100, completion_tokens=20, total_tokens=120)
        usage_chunk.usage.prompt_tokens_details = unittest.mock.MagicMock(cached_tokens=80)
        text_chunk = unittest.mock.MagicMock(spec=["choices"])
        text_chunk.choices = [mock_choice]

        async def mock_aiter(*args, **kwargs):
            yield usage_chunk
            yield text_chunk

        mock_response = unittest.mock.MagicMock()
        mock_response.__aiter__ = mock_aiter

        pricing = {"prompt": 0.01, "completion": 0.03}

        # Anthropic path: the agent routes through AnthropicAdapter.stream_chat,
        # which yields normalized adapter_usage events. Mock the adapter to emit
        # the cached-usage event plus a terminal text chunk so the loop finishes.
        class _FakeAnthropicAdapter:
            async def stream_chat(self, *args, **kwargs):
                yield ("adapter_usage", dict(cached_usage))
                yield ("adapter_text", "done")

        agent_openai = BaseAgent(
            api_key="t",
            model="test-model",
            base_url="http://t",
            system_prompt="t",
            provider_key="tprov",
            api_type="openai",
        )
        self.addAsyncCleanup(agent_openai.close)
        agent_anthropic = BaseAgent(
            api_key="t",
            model="test-model",
            base_url="http://t",
            system_prompt="t",
            provider_key="tprov",
            api_type="anthropic",
        )
        self.addAsyncCleanup(agent_anthropic.close)

        with patch.object(catalog, "get_model_pricing", return_value=pricing):
            with patch.object(
                agent_openai.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
            ) as mock_create:
                mock_create.return_value = mock_response
                async for _ in agent_openai.stream_steps("hi"):
                    pass
            with patch("core.adapters.get_adapter", return_value=_FakeAnthropicAdapter()):
                async for _ in agent_anthropic.stream_steps("hi"):
                    pass

        # uncached_in=20, cache_read=80, out=20, prompt=0.01, completion=0.03
        # anthropic (0.1x): 20*0.01 + 80*0.01*0.1 + 20*0.03 = 0.2 + 0.08 + 0.6 = 0.88
        # openai    (0.5x): 20*0.01 + 80*0.01*0.5 + 20*0.03 = 0.2 + 0.4  + 0.6 = 1.2
        self.assertAlmostEqual(agent_anthropic.cost_usd, 0.88, places=6)
        self.assertAlmostEqual(agent_openai.cost_usd, 1.2, places=6)
        self.assertLess(agent_anthropic.cost_usd, agent_openai.cost_usd)

    def test_cost_usd_native_api_cost_precedence(self):
        agent = BaseAgent(api_key="t", model="test-model", base_url="http://t", provider_key="openrouter")
        self.addCleanup(agent.close)

        step_usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
            "cost": 0.00566,
        }
        agent._accumulate_usage(step_usage=step_usage)
        self.assertEqual(agent.cost_usd, 0.00566)

    def test_cost_usd_free_and_local_models(self):
        # Local provider (ollama)
        local_agent = BaseAgent(api_key="", model="llama3", base_url="http://localhost:11434", provider_key="ollama")
        self.addCleanup(local_agent.close)
        local_agent._accumulate_usage(step_usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500})
        self.assertEqual(local_agent.cost_usd, 0.0)

        # Free model on remote provider
        free_agent = BaseAgent(api_key="t", model="meta-llama/llama-3-8b:free", base_url="http://t", provider_key="openrouter")
        self.addCleanup(free_agent.close)
        free_agent._accumulate_usage(step_usage={"prompt_tokens": 2000, "completion_tokens": 400, "total_tokens": 2400})
        self.assertEqual(free_agent.cost_usd, 0.0)

    def test_cost_usd_explicit_cache_pricing(self):
        from unittest.mock import patch

        from core.models_catalog import catalog

        agent = BaseAgent(api_key="t", model="test-cached-model", base_url="http://t", provider_key="custom")
        self.addCleanup(agent.close)

        pricing = {
            "prompt": 0.003,
            "completion": 0.015,
            "cache_read": 0.0003,
            "cache_write": 0.00375,
        }
        step_usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
            "cache_read_tokens": 600,
            "cache_write_tokens": 200,
        }
        with patch.object(catalog, "get_model_pricing", return_value=pricing):
            agent._accumulate_usage(step_usage=step_usage)

        # uncached_in = 1000 - 600 - 200 = 200
        # cost = 200 * 0.003 + 600 * 0.0003 + 200 * 0.00375 + 200 * 0.015
        # cost = 0.6 + 0.18 + 0.75 + 3.0 = 4.53
        self.assertAlmostEqual(agent.cost_usd, 4.53, places=6)

    async def test_stream_steps_tool_call_loop(self):
        agent = BaseAgent(api_key="t", model="test-model", base_url="http://t", provider_key="tprov")
        self.addAsyncCleanup(agent.close)

        # Mock tool call chunk
        tool_call_mock = unittest.mock.MagicMock()
        tool_call_mock.index = 0
        tool_call_mock.id = "tc_1"
        tool_call_mock.function.name = "read"
        tool_call_mock.function.arguments = '{"path": "test.txt"}'

        mock_delta1 = unittest.mock.MagicMock()
        mock_delta1.reasoning_content = "Thinking about file..."
        mock_delta1.reasoning = None
        mock_delta1.model_extra = None
        mock_delta1.content = None
        mock_delta1.tool_calls = [tool_call_mock]

        chunk1 = unittest.mock.MagicMock(spec=["choices"])
        chunk1.choices = [unittest.mock.MagicMock(delta=mock_delta1)]

        mock_delta2 = unittest.mock.MagicMock()
        mock_delta2.reasoning_content = None
        mock_delta2.reasoning = None
        mock_delta2.model_extra = None
        mock_delta2.content = "File read complete"
        mock_delta2.tool_calls = None

        chunk2 = unittest.mock.MagicMock(spec=["choices"])
        chunk2.choices = [unittest.mock.MagicMock(delta=mock_delta2)]

        async def aiter1(*args, **kwargs):
            yield chunk1

        async def aiter2(*args, **kwargs):
            yield chunk2

        resp1 = unittest.mock.MagicMock()
        resp1.__aiter__ = aiter1
        resp2 = unittest.mock.MagicMock()
        resp2.__aiter__ = aiter2

        mock_responses = [resp1, resp2]

        async def mock_create(*args, **kwargs):
            return mock_responses.pop(0)

        with unittest.mock.patch.object(agent.client.chat.completions, "create", side_effect=mock_create):
            agent.tool_executor = unittest.mock.AsyncMock(return_value="file content result")
            events = []
            async for evt in agent.stream_steps("Read file test.txt"):
                events.append(evt)

        # Check reasoning content yielded
        thinking_evts = [e for e in events if e[0] in ("thinking_start", "thinking_delta")]
        self.assertTrue(len(thinking_evts) > 0)
        self.assertIn("Thinking about file...", thinking_evts[-1][1])

        # Check tool execution yielded
        tool_evts = [e for e in events if e[0] == "tool"]
        self.assertEqual(len(tool_evts), 1)

        # Check final text
        bot_texts = [e for e in events if e[0] == "bot_text"]
        self.assertIn("File read complete", bot_texts[-1][1])

        # Check reasoning_content was preserved in assistant messages in history
        assistant_msgs = [m for m in agent.history if m.get("role") == "assistant"]
        self.assertTrue(len(assistant_msgs) >= 1)
        self.assertEqual(assistant_msgs[0].get("reasoning_content"), "Thinking about file...")

    async def test_duplicate_tool_calls_are_all_executed(self):
        """Identical tool calls (same name+args) must all run, not be dropped by dedup."""
        agent = BaseAgent(api_key="t", model="test-model", base_url="http://t", provider_key="tprov")
        self.addAsyncCleanup(agent.close)

        def make_tool_call(idx, id_, args):
            tc = unittest.mock.MagicMock()
            tc.index = idx
            tc.id = id_
            tc.function.name = "read"
            tc.function.arguments = args
            return tc

        def make_chunk(tool_calls, content=None):
            delta = unittest.mock.MagicMock()
            delta.reasoning_content = None
            delta.reasoning = None
            delta.model_extra = None
            delta.content = content
            delta.tool_calls = tool_calls
            chunk = unittest.mock.MagicMock(spec=["choices"])
            chunk.choices = [unittest.mock.MagicMock(delta=delta)]
            return chunk

        # Two identical tool calls in one assistant turn.
        tool_chunks = [
            make_chunk([make_tool_call(0, "tc_1", '{"path": "a.txt"}')]),
            make_chunk([make_tool_call(1, "tc_2", '{"path": "a.txt"}')]),
        ]
        text_chunk = make_chunk(None, content="done")

        async def aiter_for(chunks):
            for c in chunks:
                yield c

        resp_tools = unittest.mock.MagicMock()
        resp_tools.__aiter__ = lambda *a, **k: aiter_for(tool_chunks)
        resp_text = unittest.mock.MagicMock()
        resp_text.__aiter__ = lambda *a, **k: aiter_for([text_chunk])

        mock_responses = [resp_tools, resp_text]

        async def mock_create(*args, **kwargs):
            return mock_responses.pop(0)

        executed = []

        async def fake_execute(name, args, app=None):
            executed.append((name, dict(args)))
            return "result"

        with unittest.mock.patch.object(agent.client.chat.completions, "create", side_effect=mock_create):
            agent.tool_executor = unittest.mock.AsyncMock(side_effect=fake_execute)
            events = []
            async for evt in agent.stream_steps("read twice"):
                events.append(evt)

        tool_evts = [e for e in events if e[0] == "tool"]
        self.assertEqual(len(tool_evts), 2)
        self.assertEqual(len(executed), 2)
        self.assertEqual(executed, [("read", {"path": "a.txt"}), ("read", {"path": "a.txt"})])


class TestAgentStreamEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Stream_steps edge cases: MCP readiness, attachments, adapters, data chunks,
    thinking ordering, and malformed tool arguments."""

    def _make_agent(self, **kwargs):
        agent = make_agent(**kwargs)
        self.addAsyncCleanup(agent.close)
        return agent

    async def test_mcp_manager_ensure_tools_called_outside_pytest(self):
        agent = self._make_agent()
        fake_mgr = unittest.mock.MagicMock()
        fake_mgr.ensure_tools_ready_async = unittest.mock.AsyncMock(return_value=None)
        with unittest.mock.patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}):
            with unittest.mock.patch("core.infrastructure.mcp.get_mcp_manager", return_value=fake_mgr):
                with unittest.mock.patch.object(
                    agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
                ) as mock_create:
                    mock_create.side_effect = Exception("Stop stream")
                    try:
                        async for _ in agent.stream_steps("hi"):
                            pass
                    except Exception:
                        pass
        fake_mgr.ensure_tools_ready_async.assert_called_once()

        # Failure inside ensure_tools_ready_async is swallowed (try/except pass).
        fake_mgr.ensure_tools_ready_async = unittest.mock.AsyncMock(side_effect=RuntimeError("mcp down"))
        with unittest.mock.patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}):
            with unittest.mock.patch("core.infrastructure.mcp.get_mcp_manager", return_value=fake_mgr):
                with unittest.mock.patch.object(
                    agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
                ) as mock_create:
                    mock_create.side_effect = Exception("Stop stream")
                    try:
                        async for _ in agent.stream_steps("hi"):
                            pass
                    except Exception:
                        pass
        fake_mgr.ensure_tools_ready_async.assert_called()

    async def test_attachments_processed_into_image_url(self):
        agent = self._make_agent()
        img_json = json.dumps({"base64": "QUFB", "media_type": "image/png", "detail": "high"})

        def fake_process(path):
            if str(path).endswith("bad.png"):
                raise RuntimeError("cannot read")
            return img_json

        agent.image_processor = fake_process
        logged = []
        with unittest.mock.patch(
            "core.base_provider.agent.logger.warning", side_effect=lambda *a, **k: logged.append(a)
        ):
            with unittest.mock.patch.object(
                agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
            ) as mock_create:
                mock_create.return_value = _MockStream([_text_chunk("ok")])
                events = []
                async for evt in agent.stream_steps(
                    "Look", attachments=[_Attachment("a.png"), _Attachment("bad.png")]
                ):
                    events.append(evt)

        self.assertEqual(events[-1], ("bot_text", "ok", ""))
        self.assertTrue(any("Error processing attachment image" in str(p) for p in logged))
        messages = mock_create.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        self.assertEqual(user_content[0], {"type": "text", "text": "Look"})
        self.assertEqual(
            user_content[1],
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUFB", "detail": "high"}},
        )

    async def test_adapter_tool_call_usage_and_text_stream(self):
        agent = self._make_agent(api_type="anthropic")

        class _FakeAdapter:
            def __init__(self, streams):
                self._streams = list(streams)

            async def stream_chat(self, *args, **kwargs):
                if self._streams:
                    for item in self._streams.pop(0):
                        yield item

        streams = [
            [
                ("adapter_tool_call", {"id": "c1", "name": "read", "arguments": '{"path": "a.txt"}'}),
                ("adapter_tool_call", {"name": "shell", "arguments": "{}"}),
                (
                    "adapter_usage",
                    {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cache_read_tokens": 0},
                ),
            ],
            [("adapter_text", "final answer")],
        ]
        with unittest.mock.patch("core.adapters.get_adapter", return_value=_FakeAdapter(streams)):
            agent.tool_executor = unittest.mock.AsyncMock(return_value="tool ok")
            events = []
            async for evt in agent.stream_steps("run tools"):
                events.append(evt)

        tool_evts = [e for e in events if e[0] == "tool"]
        self.assertEqual(len(tool_evts), 2)
        self.assertEqual(tool_evts[0][3], {"path": "a.txt"})
        self.assertEqual(events[-1], ("bot_text", "final answer", ""))
        # Tool call without explicit id falls back to "call_{idx}".
        assistant_msgs = [m for m in agent.history if m.get("role") == "assistant" and m.get("tool_calls")]
        tc_ids = [tc["id"] for m in assistant_msgs for tc in m["tool_calls"]]
        self.assertIn("c1", tc_ids)
        self.assertIn("call_1", tc_ids)

    async def test_extra_body_passed_to_create(self):
        agent = self._make_agent(extra_body={"temperature": 0.2})
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = _MockStream([_text_chunk("hi")])
            events = []
            async for evt in agent.stream_steps("hello"):
                events.append(evt)

        self.assertEqual(events[-1], ("bot_text", "hi", ""))
        self.assertEqual(mock_create.call_args.kwargs["extra_body"], {"temperature": 0.2})

    async def test_stream_chunk_with_data_attribute(self):
        agent = self._make_agent()
        dict_choice = unittest.mock.MagicMock(delta=_delta(content="from dict data"))
        obj_choice = unittest.mock.MagicMock(delta=_delta(content="from obj data"))
        chunks = [
            {"data": {"choices": [dict_choice]}},
            _Chunk(choices=None, data=unittest.mock.MagicMock(choices=[obj_choice])),
        ]
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = _MockStream(chunks)
            events = []
            async for evt in agent.stream_steps("hi"):
                events.append(evt)

        bot_deltas = [e[1] for e in events if e[0] == "bot_delta"]
        self.assertEqual(bot_deltas, ["from dict data", "from obj data"])
        self.assertEqual(events[-1], ("bot_text", "from dict datafrom obj data", ""))

    async def test_thinking_end_before_content(self):
        agent = self._make_agent()
        chunks = [
            _Chunk(choices=[unittest.mock.MagicMock(delta=_delta(reasoning_content="thinking hard"))]),
            _text_chunk("answer"),
        ]
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = _MockStream(chunks)
            events = []
            async for evt in agent.stream_steps("hi"):
                events.append(evt)

        self.assertIn(("thinking_start", "Thinking...", ""), events)
        self.assertIn(("thinking_delta", "thinking hard", ""), events)
        thinking_end_idx = next(i for i, e in enumerate(events) if e[0] == "thinking_end")
        self.assertLess(thinking_end_idx, next(i for i, e in enumerate(events) if e[0] == "bot_delta"))
        self.assertEqual(events[-1], ("bot_text", "answer", ""))

    async def test_thinking_end_at_stream_end(self):
        agent = self._make_agent()
        chunk = _Chunk(choices=[unittest.mock.MagicMock(delta=_delta(reasoning_content="deep thought"))])
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = _MockStream([chunk])
            events = []
            async for evt in agent.stream_steps("hi"):
                events.append(evt)

        thinking_ends = [e for e in events if e[0] == "thinking_end"]
        self.assertEqual(len(thinking_ends), 1)
        self.assertEqual(thinking_ends[0][2], "deep thought")
        self.assertEqual(events[-1], ("bot_text", "", ""))

    async def test_invalid_json_tool_arguments(self):
        # Malformed tool-call JSON is normalized to {} by parse_tool_call_args
        # and the tool executes with empty args (invalid-arguments surfacing was
        # removed in favor of the shared parse helper).
        agent = self._make_agent()
        first = _MockStream([_tool_call_chunk(0, "tc_1", "read", "not-json{")])
        second = _MockStream([_text_chunk("ok")])
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.side_effect = [first, second]
            agent.tool_executor = unittest.mock.AsyncMock()
            events = []
            async for evt in agent.stream_steps("read it"):
                events.append(evt)

        self.assertEqual(events[-1], ("bot_text", "ok", ""))
        tool_evts = [e for e in events if e[0] == "tool"]
        self.assertEqual(tool_evts[0][2], "")  # read without path -> empty target chip
        agent.tool_executor.assert_called_once()


class TestDrainForeignSession(unittest.IsolatedAsyncioTestCase):
    async def test_drain_keeps_foreign_session_and_consumes_own(self):
        """Foreign-session messages must not cause an infinite loop and must stay queued."""
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        self.addAsyncCleanup(agent.close)

        app = _make_app_mock(
            current_session_id="sess_current",
            message_queue=[
                ("foreign", True, None, "sess_other"),
                ("own", True, None, "sess_current"),
                ("foreign2", True, None, "sess_other"),
            ],
        )
        agent.app = app

        mock_chunk = unittest.mock.MagicMock(spec=["choices"])
        mock_delta = unittest.mock.MagicMock()
        mock_delta.reasoning_content = None
        mock_delta.reasoning = None
        mock_delta.model_extra = None
        mock_delta.content = "Hello world"
        mock_delta.tool_calls = None
        mock_choice = unittest.mock.MagicMock()
        mock_choice.delta = mock_delta
        mock_chunk.choices = [mock_choice]

        async def mock_aiter(*args, **kwargs):
            yield mock_chunk

        mock_response = unittest.mock.MagicMock()
        mock_response.__aiter__ = mock_aiter

        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            steps = []
            async for step in agent.stream_steps("Hi"):
                steps.append(step)

        # Own message drained into a queued_user_message event.
        queued = [s for s in steps if s[0] == "queued_user_message"]
        self.assertEqual([s[1] for s in queued], ["own"])
        # 5th element carries the queued item's display_text (None when absent).
        self.assertEqual([s[4] for s in queued], [None])
        # Foreign-session messages left in the queue untouched.
        self.assertEqual([item[0] for item in app.message_queue], ["foreign", "foreign2"])

    async def test_drain_only_foreign_does_not_loop(self):
        """A queue containing only foreign-session messages must terminate."""
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        self.addAsyncCleanup(agent.close)

        app = _make_app_mock(
            current_session_id="sess_current",
            message_queue=[
                ("foreign", True, None, "sess_other"),
                ("foreign2", True, None, "sess_other"),
            ],
        )
        agent.app = app

        mock_chunk = unittest.mock.MagicMock(spec=["choices"])
        mock_delta = unittest.mock.MagicMock()
        mock_delta.reasoning_content = None
        mock_delta.reasoning = None
        mock_delta.model_extra = None
        mock_delta.content = "Hello world"
        mock_delta.tool_calls = None
        mock_choice = unittest.mock.MagicMock()
        mock_choice.delta = mock_delta
        mock_chunk.choices = [mock_choice]

        async def mock_aiter(*args, **kwargs):
            yield mock_chunk

        mock_response = unittest.mock.MagicMock()
        mock_response.__aiter__ = mock_aiter

        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            steps = []
            async for step in agent.stream_steps("Hi"):
                steps.append(step)

        # No own messages drained; foreign remain; no queued_user_message events.
        self.assertFalse(any(s[0] == "queued_user_message" for s in steps))
        self.assertEqual([item[0] for item in app.message_queue], ["foreign", "foreign2"])

    async def test_subagent_pending_messages_drained_in_stream_steps(self):
        """Subagents must drain pending_messages between stream steps."""
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        self.addAsyncCleanup(agent.close)
        agent.is_subagent = True

        sess = unittest.mock.MagicMock()
        sess.pending_messages = ["follow up 1", "follow up 2"]
        agent.session = sess

        mock_chunk = unittest.mock.MagicMock(spec=["choices"])
        mock_delta = unittest.mock.MagicMock()
        mock_delta.reasoning_content = None
        mock_delta.reasoning = None
        mock_delta.model_extra = None
        mock_delta.content = "Subagent reply"
        mock_delta.tool_calls = None
        mock_choice = unittest.mock.MagicMock()
        mock_choice.delta = mock_delta
        mock_chunk.choices = [mock_choice]

        async def mock_aiter(*args, **kwargs):
            yield mock_chunk

        mock_response = unittest.mock.MagicMock()
        mock_response.__aiter__ = mock_aiter

        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            steps = []
            async for step in agent.stream_steps("Hi"):
                steps.append(step)

        queued = [s for s in steps if s[0] == "queued_user_message"]
        self.assertEqual([s[1] for s in queued], ["follow up 1", "follow up 2"])
        self.assertEqual(sess.pending_messages, [])
