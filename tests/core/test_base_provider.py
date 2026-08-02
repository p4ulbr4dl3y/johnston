import os
import shutil
import tempfile
import unittest
import unittest.mock

from core.base_provider import BaseAgent
from tools.registry import execute_tool


class TestBaseProviderTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    async def test_create_and_read_tool(self):
        file_path = os.path.join(self.test_dir, "test.txt")

        # Test Create
        res_create = await execute_tool("create", {"path": file_path, "content": "hello world"})
        self.assertIn("Success", res_create)
        self.assertTrue(os.path.exists(file_path))

        # Test Read
        res_read = await execute_tool("read", {"path": file_path})
        self.assertIn("hello world", res_read)

    async def test_read_missing_file(self):
        file_path = os.path.join(self.test_dir, "missing.txt")
        res_read = await execute_tool("read", {"path": file_path})
        self.assertIn("Error", res_read)

    async def test_edit_tool(self):
        file_path = os.path.join(self.test_dir, "edit_test.txt")
        await execute_tool("create", {"path": file_path, "content": "line1\nline2\nline3"})

        # Test valid Edit
        res_edit = await execute_tool("edit", {
            "path": file_path,
            "old_string": "line2",
            "new_string": "line_two"
        })
        self.assertIn("line2", res_edit)  # check diff contains old text
        self.assertIn("line_two", res_edit)  # check diff contains new text

        # Verify content
        with open(file_path, "r") as f:
            content = f.read()
        self.assertEqual(content, "line1\nline_two\nline3")

    async def test_read_line_range_pagination(self):
        file_path = os.path.join(self.test_dir, "range_test.txt")
        await execute_tool("create", {"path": file_path, "content": "line1\nline2\nline3\nline4"})

        res_read = await execute_tool("read", {"path": file_path, "start_line": 2, "end_line": 3})
        self.assertIn("Lines 2-3", res_read)
        self.assertIn("2 | line2", res_read)
        self.assertIn("3 | line3", res_read)
        self.assertNotIn("line1", res_read)

    async def test_edit_missing_text(self):
        file_path = os.path.join(self.test_dir, "edit_test.txt")
        await execute_tool("create", {"path": file_path, "content": "line1\nline2\nline3"})

        res_edit = await execute_tool("edit", {
            "path": file_path,
            "old_string": "missing_line",
            "new_string": "replacement"
        })
        self.assertIn("Error", res_edit)

    async def test_edit_ambiguous_occurrences(self):
        file_path = os.path.join(self.test_dir, "ambiguous_test.txt")
        await execute_tool("create", {"path": file_path, "content": "duplicate\nmiddle\nduplicate"})

        res_edit = await execute_tool("edit", {
            "path": file_path,
            "old_string": "duplicate",
            "new_string": "replacement"
        })
        self.assertIn("matches 2 occurrences", res_edit)

    async def test_shell_tool_sync(self):
        # Sync shell execution
        res_shell = await execute_tool("shell", {"command": "echo 'hello shell'"})
        self.assertEqual(res_shell.strip(), "hello shell")

    def test_init_and_compact_commands_registered(self):
        from core.commands import COMMAND_REGISTRY
        self.assertIn("/init", COMMAND_REGISTRY)
        self.assertIn("/compact", COMMAND_REGISTRY)



    async def test_compact_history_short(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)
        agent.history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"}
        ]
        success, msg = await agent.compact_history()
        self.assertFalse(success)
        self.assertIn("too short", msg)

    async def test_compact_history_opencode_template(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)
        agent.history = [
            {"role": "user", "content": "Fix bug in auth.py"},
            {"role": "assistant", "content": "Checking auth.py", "tool_calls": [{"function": {"name": "read", "arguments": "auth.py"}}]},
            {"role": "tool", "content": "def login(): return False"},
            {"role": "user", "content": "Change to return True"},
            {"role": "assistant", "content": "Updated auth.py"},
            {"role": "user", "content": "Run tests"}
        ]

        # Mock OpenAI chat completion call
        mock_response = unittest.mock.MagicMock()
        mock_choice = unittest.mock.MagicMock()
        mock_choice.message.content = "## Objective\n- Fix auth.py\n\n## Work State\n### Completed\n- Updated login\n\n## Next Move\n1. Run tests\n\n## Relevant Files\n- auth.py"
        mock_response.choices = [mock_choice]

        with unittest.mock.patch.object(agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            success, msg = await agent.compact_history()

            self.assertTrue(success)
            self.assertIn("compacted successfully", msg)
            self.assertEqual(len(agent.history), 4) # 1 summary + 3 tail messages starting at user turn
            self.assertIn("<conversation-checkpoint>", agent.history[0]["content"])
            self.assertIn("## Objective", agent.history[0]["content"])
            self.assertIn("auth.py", agent.history[0]["content"])


    async def test_auto_compaction_trigger(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)
        agent.history = [
            {"role": "user", "content": "a" * 200},
            {"role": "assistant", "content": "b" * 200},
            {"role": "user", "content": "c" * 200},
            {"role": "assistant", "content": "d" * 200},
            {"role": "user", "content": "e" * 200},
        ]
        compacted = False
        async def mock_compact():
            nonlocal compacted
            compacted = True
            return True, "compacted"

        with unittest.mock.patch("core.base_provider.BaseAgent.context_limit", new_callable=unittest.mock.PropertyMock) as mock_limit:
            mock_limit.return_value = 100
            with unittest.mock.patch.object(agent, "compact_history", new_callable=unittest.mock.AsyncMock) as mock_comp:
                mock_comp.return_value = (True, "compacted")
                with unittest.mock.patch.object(agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock) as mock_create:
                    mock_create.side_effect = Exception("Stop stream")
                    try:
                        async for _ in agent.stream_steps("trigger"):
                            pass
                    except Exception:
                        pass
                    mock_comp.assert_called_once()

    async def test_manage_task_tool(self):
        class DummyApp:
            background_tasks = []

        app = DummyApp()
        res_list = await execute_tool("manage_task", {"action": "list"}, app=app)
        self.assertIn("No background tasks currently active", res_list)

    async def test_task_tool_foreground(self):
        class DummySubAgent:
            system_prompt = "system"
            tools = []
            async def stream_steps(self, prompt):
                yield ("bot_text", "Subagent answer for: " + prompt, "")

        class DummyPM:
            def create_active_agent(self):
                return DummySubAgent()

        class DummyApp:
            pm = DummyPM()

        app = DummyApp()
        res = await execute_tool("subagent", {"prompt": "do research", "description": "research task"}, app=app)
        self.assertIn("launched in background", res)

    async def test_task_tool_background(self):
        class DummySubAgent:
            system_prompt = "system"
            tools = []
            async def stream_steps(self, prompt):
                yield ("bot_text", "BG Subagent answer", "")

        class DummyPM:
            def create_active_agent(self):
                return DummySubAgent()

        class DummyApp:
            pm = DummyPM()
            background_tasks = []
            notified = []

            def notify(self, msg):
                self.notified.append(msg)

            def refresh_status_footer(self):
                pass

            def generate_ai_response(self, text, show_in_ui=False):
                pass

        app = DummyApp()
        res = await execute_tool("subagent", {"prompt": "bg task", "description": "bg job", "background": True}, app=app)
        self.assertIn("launched in background", res)
        self.assertEqual(len(app.background_tasks), 1)
        self.assertTrue(app.background_tasks[0].task_id.startswith("subagent-"))

    def test_truncate_output_helper(self):
        from tools.base import truncate_output
        short_text = "hello"
        self.assertEqual(truncate_output(short_text, max_chars=10), "hello")

        long_text = "a" * 100
        truncated = truncate_output(long_text, max_chars=10, hint="Use line ranges.", save_log=False)
        self.assertTrue(truncated.startswith("aaaaaaaaaa"))
        self.assertIn("Output truncated at 10 chars. Use line ranges.", truncated)

    def test_agent_cost_usd_calculation(self):
        agent = BaseAgent(api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov")
        self.assertEqual(agent.cost_usd, 0.0)
        metrics = agent.get_metrics()
        self.assertEqual(metrics["cost_usd"], 0.0)

        agent.cost_usd = 0.0025
        self.assertEqual(agent.get_metrics()["cost_usd"], 0.0025)

        agent.clear_history()
        self.assertEqual(agent.cost_usd, 0.0)

    def test_truncate_history_to_user_message(self):
        agent = BaseAgent(api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov")
        agent.history = [
            {"role": "user", "content": "Msg 0"},
            {"role": "assistant", "content": "Resp 0"},
            {"role": "user", "content": "Msg 1"},
            {"role": "assistant", "content": "Resp 1"},
            {"role": "user", "content": "Msg 2"},
            {"role": "assistant", "content": "Resp 2"},
        ]

        # Truncate to index 1 (keep Msg 0 and Resp 0, drop Msg 1 and later)
        agent.truncate_history_to_user_message(1)
        self.assertEqual(len(agent.history), 2)
        self.assertEqual(agent.history[0]["content"], "Msg 0")
        self.assertEqual(agent.history[1]["content"], "Resp 0")

        # Truncate to index 0 (clears all)
        agent.truncate_history_to_user_message(0)
        self.assertEqual(len(agent.history), 0)


    async def test_stream_steps_history_updated_on_exception(self):
        agent = BaseAgent(api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov")
        agent.client = unittest.mock.AsyncMock()
        agent.client.chat.completions.create.side_effect = Exception("API connection error")

        steps = []
        async for step in agent.stream_steps("Hello test"):
            steps.append(step)

        # Confirm user prompt is saved into history despite exception
        self.assertEqual(len(agent.history), 1)
        self.assertEqual(agent.history[0]["role"], "user")
        self.assertEqual(agent.history[0]["content"], "Hello test")

    async def test_stream_steps_without_chunk_usage(self):
        agent = BaseAgent(api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov")
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

        with unittest.mock.patch.object(agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock) as mock_create:
            mock_create.return_value = mock_response

            steps = []
            async for step in agent.stream_steps("Hi"):
                steps.append(step)

            self.assertTrue(len(steps) > 0)
            self.assertIn(("bot_delta", "Hello world", ""), steps)
            self.assertEqual(steps[-1], ("bot_text", "Hello world", ""))
            self.assertGreater(agent.tokens_input, 0)
            self.assertGreater(agent.tokens_output, 0)

    async def test_sanitize_history_for_model(self):
        agent = BaseAgent(api_key="test", model="non-vision-model", base_url="http://test", provider_key="opencode")
        self.addAsyncCleanup(agent.close)

        history = [
            {"role": "user", "content": "Look at this"},
            {"role": "assistant", "content": "Done", "tool_calls": [{"id": "call_1", "function": {"name": "read"}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "read", "content": "file contents"},
            {"role": "tool", "tool_call_id": "call_orphan", "name": "edit", "content": "orphan content"}
        ]

        sanitized = agent.sanitize_history_for_model(history)
        self.assertEqual(len(sanitized), 4)

        # Valid tool output preserved
        self.assertEqual(sanitized[2]["role"], "tool")
        self.assertEqual(sanitized[2]["tool_call_id"], "call_1")

        # Orphan tool converted to user role
        self.assertEqual(sanitized[3]["role"], "user")
        self.assertIn("orphan content", sanitized[3]["content"])

    def test_default_max_tokens_is_8192(self):
        agent = BaseAgent(api_key="t", model="m", base_url="http://t", system_prompt="t", provider_key="p")
        self.addAsyncCleanup(agent.close)
        # Raised from 4096 so long code answers are not truncated mid-generation.
        self.assertEqual(agent.max_tokens, 8192)

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
        usage_chunk.usage = unittest.mock.MagicMock(
            prompt_tokens=100, completion_tokens=20, total_tokens=120
        )
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

        agent_openai = BaseAgent(api_key="t", model="test-model", base_url="http://t", system_prompt="t", provider_key="tprov", api_type="openai")
        self.addAsyncCleanup(agent_openai.close)
        agent_anthropic = BaseAgent(api_key="t", model="test-model", base_url="http://t", system_prompt="t", provider_key="tprov", api_type="anthropic")
        self.addAsyncCleanup(agent_anthropic.close)

        with patch.object(catalog, "get_model_pricing", return_value=pricing):
            with patch.object(agent_openai.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock) as mock_create:
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

    def test_is_retryable_error(self):
        agent = BaseAgent(api_key="t", model="test-model", base_url="http://t", provider_key="tprov")

        # Retryable errors
        self.assertTrue(agent._is_retryable_error(RuntimeError("Stream chunk timeout: No response received from provider 'test' for 30.0s.")))
        self.assertTrue(agent._is_retryable_error(TimeoutError("Connection timed out")))
        self.assertTrue(agent._is_retryable_error(Exception("HTTP 429 Too Many Requests")))
        self.assertTrue(agent._is_retryable_error(Exception("HTTP 502 Bad Gateway")))

        # Non-retryable errors
        self.assertFalse(agent._is_retryable_error(Exception("Invalid API key provided")))
        self.assertFalse(agent._is_retryable_error(Exception("HTTP 401 Unauthorized")))
        self.assertFalse(agent._is_retryable_error(Exception("context_length_exceeded: maximum context length is 4096 tokens")))

    async def test_stream_steps_retry_success(self):
        agent = BaseAgent(api_key="t", model="test-model", base_url="http://t", provider_key="tprov", max_retries=3, retry_delay=0.01)
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
        # Verify retry notice was yielded to UI
        retry_notices = [e for e in events if e[0] == "thinking" and "[Retry 1/3]" in e[1]]
        self.assertEqual(len(retry_notices), 1)
        # Verify bot_text event
        bot_texts = [e for e in events if e[0] == "bot_text"]
        self.assertTrue(any("hello after retry" in e[1] for e in bot_texts))

    async def test_stream_steps_non_retryable_fails_immediately(self):
        agent = BaseAgent(api_key="t", model="test-model", base_url="http://t", provider_key="tprov", max_retries=3, retry_delay=0.01)
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
        api_errors = [e for e in events if e[0] == "compaction_divider" and "API Error" in e[1]]
        self.assertEqual(len(api_errors), 1)
        self.assertIn("Invalid API key", api_errors[0][1])

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
            with unittest.mock.patch("core.base_provider.execute_tool", new_callable=unittest.mock.AsyncMock, return_value="file content result"):
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

    def test_vision_error_sanitization_and_hint(self):
        agent = BaseAgent(api_key="t", model="non-vision-model", base_url="http://t", provider_key="tprov")
        self.addAsyncCleanup(agent.close)

        err = Exception("No endpoints found that support image input")
        self.assertTrue(agent._is_vision_error(err))

        messages = [
            {"role": "user", "content": "Look at image"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "function": {"name": "read", "arguments": '{"path":"1.png"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": '{"type": "image", "path": "1.png", "base64": "QUFB"}'},
            {"role": "user", "content": [{"type": "text", "text": "Preview:"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUFB"}}]}
        ]

        sanitized = agent._sanitize_vision_error_messages(messages)
        # Verify user image_url message was removed
        self.assertEqual(len(sanitized), 3)
        # Verify tool content was replaced with hint
        tool_msg = sanitized[2]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertIn("[Hint: You do not support vision. Tell user you cannot view images. Do not retry.]", tool_msg["content"])

    async def test_stream_cancelled_error_records_tokens(self):
        import asyncio
        agent = BaseAgent(api_key="t", model="m", base_url="http://t", provider_key="tprov")
        self.addAsyncCleanup(agent.close)

        chunk = unittest.mock.MagicMock()
        chunk.usage = None
        choice = unittest.mock.MagicMock()
        delta = unittest.mock.NonCallableMagicMock(spec=["content", "tool_calls", "reasoning_content", "reasoning", "model_extra"])
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

        with unittest.mock.patch.object(agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock, return_value=MockAsyncStream()):
            gen = agent.stream_steps("Hello cancelled")
            await gen.__anext__()
            try:
                await gen.athrow(asyncio.CancelledError())
            except (asyncio.CancelledError, StopAsyncIteration):
                pass

        self.assertGreater(agent.tokens_input, 0)
        self.assertGreaterEqual(agent.total_tokens, agent.tokens_input)


if __name__ == "__main__":
    unittest.main()

