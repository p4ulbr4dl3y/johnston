import asyncio
import json
import os
import shutil
import tempfile
import unittest
import unittest.mock

from core.base_provider import BaseAgent
from core.domain.defaults.errors import ToolResult
from tools.registry import execute_tool


class TestBaseProviderTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        pm.set_session_override("shell", "allow")
        pm.set_session_override("manage_shell", "allow")
        pm.set_session_override("invoke_subagent", "allow")
        # Grant the file tools that used to be 'allow' via the removed read/write groups.
        pm.set_session_override("read", "allow")
        pm.set_session_override("create", "allow")
        pm.set_session_override("edit", "allow")
        pm.set_session_override("multi_edit", "allow")

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_create_and_read_tool(self):
        file_path = os.path.join(self.test_dir, "test.txt")

        # Test Create
        res_create = await execute_tool("create", {"path": file_path, "content": "hello world"})
        self.assertIn("file", res_create.content)
        self.assertTrue(os.path.exists(file_path))

        # Test Read
        res_read = await execute_tool("read", {"path": file_path})
        self.assertIn("hello world", res_read.content)

    async def test_read_missing_file(self):
        file_path = os.path.join(self.test_dir, "missing.txt")
        res_read = await execute_tool("read", {"path": file_path})
        self.assertIn("ERR: file", res_read.content)
        self.assertTrue(res_read.is_error)

    async def test_edit_tool(self):
        file_path = os.path.join(self.test_dir, "edit_test.txt")
        await execute_tool("create", {"path": file_path, "content": "line1\nline2\nline3"})

        # Test valid Edit
        res_edit = await execute_tool("edit", {"path": file_path, "old_str": "line2", "new_str": "line_two"})
        self.assertIn("line2", res_edit.content)  # check diff contains old text
        self.assertIn("line_two", res_edit.content)  # check diff contains new text

        # Verify content
        with open(file_path, "r") as f:
            content = f.read()
        self.assertEqual(content, "line1\nline_two\nline3")

    async def test_read_line_range_pagination(self):
        file_path = os.path.join(self.test_dir, "range_test.txt")
        await execute_tool("create", {"path": file_path, "content": "line1\nline2\nline3\nline4"})

        res_read = await execute_tool("read", {"path": file_path, "start_line": 2, "end_line": 3})
        self.assertIn("Lines 2-3", res_read.content)
        self.assertIn("2 | line2", res_read.content)
        self.assertIn("3 | line3", res_read.content)
        self.assertNotIn("line1", res_read.content)

    async def test_edit_missing_text(self):
        file_path = os.path.join(self.test_dir, "edit_test.txt")
        await execute_tool("create", {"path": file_path, "content": "line1\nline2\nline3"})

        res_edit = await execute_tool(
            "edit", {"path": file_path, "old_str": "missing_line", "new_str": "replacement"}
        )
        self.assertIn("ERR: match: exact block not found", res_edit.content)

    async def test_edit_ambiguous_occurrences(self):
        file_path = os.path.join(self.test_dir, "ambiguous_test.txt")
        await execute_tool("create", {"path": file_path, "content": "duplicate\nmiddle\nduplicate"})

        res_edit = await execute_tool(
            "edit", {"path": file_path, "old_str": "duplicate", "new_str": "replacement"}
        )
        self.assertIn("matches 2 occurrences", res_edit.content)

    async def test_shell_tool_sync(self):
        # Sync shell execution
        res_shell = await execute_tool("shell", {"command": "echo 'hello shell'"})
        self.assertEqual(res_shell.content.strip(), "hello shell")

    def test_compact_command_registered(self):
        from widgets.app.dispatch import COMMAND_REGISTRY

        self.assertIn("/compact", COMMAND_REGISTRY)

    async def test_compact_history_short(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)
        agent.history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        success, msg = await agent.compact_history()
        self.assertFalse(success)
        self.assertIn("too short", msg)

    async def test_compact_history_opencode_template(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)
        agent.history = [
            {"role": "user", "content": "Fix bug in auth.py"},
            {
                "role": "assistant",
                "content": "Checking auth.py",
                "tool_calls": [{"function": {"name": "read", "arguments": "auth.py"}}],
            },
            {"role": "tool", "content": "def login(): return False"},
            {"role": "user", "content": "Change to return True"},
            {"role": "assistant", "content": "Updated auth.py"},
            {"role": "user", "content": "Run tests"},
        ]

        # Mock OpenAI chat completion call
        mock_response = unittest.mock.MagicMock()
        mock_choice = unittest.mock.MagicMock()
        mock_choice.message.content = "## Objective\n- Fix auth.py\n\n## Work State\n### Completed\n- Updated login\n\n## Next Move\n1. Run tests\n\n## Relevant Files\n- auth.py"
        mock_response.choices = [mock_choice]

        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            success, msg = await agent.compact_history()

            self.assertTrue(success)
            self.assertIn("compacted successfully", msg)
            self.assertEqual(len(agent.history), 4)  # 1 summary + 3 tail messages starting at user turn
            self.assertIn("<conversation-checkpoint>", agent.history[0]["content"])
            self.assertIn("## Objective", agent.history[0]["content"])
            self.assertIn("auth.py", agent.history[0]["content"])

    async def test_compact_history_drops_empty_tool_content(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)
        # A tool message with empty content serializes to a user message with
        # empty content, which OpenAI/DeepSeek reject with 400. It must be dropped.
        agent.history = [
            {"role": "user", "content": "Run the build"},
            {"role": "assistant", "content": "Running"},
            {"role": "tool", "content": ""},
            {"role": "user", "content": "Keep going"},
            {"role": "assistant", "content": "Done"},
            {"role": "user", "content": "Final check"},
        ]

        mock_response = unittest.mock.MagicMock()
        mock_choice = unittest.mock.MagicMock()
        mock_choice.message.content = "## Objective\n- Build\n\n## Next Move\n1. Continue"
        mock_response.choices = [mock_choice]

        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            success, msg = await agent.compact_history()
            self.assertTrue(success)
            # The empty tool message must not produce an empty user message.
            self.assertNotIn(
                {"role": "user", "content": ""},
                agent.history,
            )

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

        with unittest.mock.patch(
            "core.base_provider.BaseAgent.context_limit", new_callable=unittest.mock.PropertyMock
        ) as mock_limit:
            mock_limit.return_value = 100
            with unittest.mock.patch.object(
                agent, "compact_history", new_callable=unittest.mock.AsyncMock
            ) as mock_comp:
                mock_comp.return_value = (True, "compacted")
                with unittest.mock.patch.object(
                    agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
                ) as mock_create:
                    mock_create.side_effect = Exception("Stop stream")
                    try:
                        async for _ in agent.stream_steps("trigger"):
                            pass
                    except Exception:
                        pass
                    mock_comp.assert_called_once()

    async def test_manage_shell_tool(self):
        class DummyApp:
            def __init__(self):
                from core.infrastructure.tasks.manager import TaskManager

                self.task_manager = TaskManager()

        app = DummyApp()
        res_list = await execute_tool("manage_shell", {"action": "list"}, app=app)
        self.assertIn("no tasks active", res_list.content)

    async def test_task_tool_foreground(self):
        import tempfile

        from core.session_manager import SessionStore

        _tmp = tempfile.TemporaryDirectory()
        self.addCleanup(_tmp.cleanup)
        _store = SessionStore(project_path=_tmp.name)
        _old = SessionStore._instance
        SessionStore._instance = _store
        self.addCleanup(setattr, SessionStore, "_instance", _old)

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
        res = await execute_tool(
            "invoke_subagent", {"prompt": "do research", "description": "research task", "branch": "main"}, app=app
        )
        self.assertIn("subagent 'research task' launched", res.content)

    async def test_task_tool_background(self):
        import tempfile

        from core.session_manager import SessionStore

        _tmp = tempfile.TemporaryDirectory()
        self.addCleanup(_tmp.cleanup)
        _store = SessionStore(project_path=_tmp.name)
        _old = SessionStore._instance
        SessionStore._instance = _store
        self.addCleanup(setattr, SessionStore, "_instance", _old)

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
            notified = []

            def notify(self, msg):
                self.notified.append(msg)

            def refresh_status_footer(self):
                pass

            def generate_ai_response(self, text, show_in_ui=False):
                pass

        app = DummyApp()
        res = await execute_tool(
            "invoke_subagent",
            {"prompt": "bg task", "description": "bg job", "branch": "main"},
            app=app,
        )
        self.assertIn("subagent 'bg job' launched", res.content)
        sessions = _store.list(kind="subagent")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].description, "bg job")
        self.assertEqual(sessions[0].status, "running")

    def test_truncate_output_helper(self):
        from tools.base import truncate_output

        short_text = "hello"
        self.assertEqual(truncate_output(short_text, max_chars=10), "hello")

        long_text = "a" * 100
        truncated = truncate_output(long_text, max_chars=10, hint="Use line ranges.", save_log=False)
        self.assertTrue(truncated.startswith("aaaaaaaaaa"))
        self.assertIn("Output truncated at 10 chars", truncated)
        self.assertIn("Use line ranges.", truncated)

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

    def test_truncate_history_to_user_message(self):
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
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

    def test_truncate_skips_checkpoint_and_interruption_notes(self):
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        agent.history = [
            {"role": "user", "content": "<conversation-checkpoint>\n<summary>earlier work</summary>\n</conversation-checkpoint>"},
            {"role": "user", "content": "Tail 0"},
            {"role": "assistant", "content": "Resp 0"},
            {"role": "user", "content": "[System Note: Response interrupted by user]"},
            {"role": "user", "content": "Tail 1"},
            {"role": "assistant", "content": "Resp 1"},
        ]

        # History has only two real user turns (checkpoint + interruption note
        # are not user turns). Truncate to the 2nd real user turn -> keep Tail 0.
        agent.truncate_history_to_user_message(1)
        contents = [m["content"] for m in agent.history]
        self.assertEqual(contents, ["<conversation-checkpoint>\n<summary>earlier work</summary>\n</conversation-checkpoint>", "Tail 0", "Resp 0"])

        # Truncate to the 1st real user turn -> drops the checkpoint too.
        agent.truncate_history_to_user_message(0)
        self.assertEqual(agent.history, [])

    def test_truncate_clears_when_user_turn_is_compacted(self):
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        agent.history = [
            {"role": "user", "content": "<conversation-checkpoint>\n<summary>earlier work</summary>\n</conversation-checkpoint>"},
            {"role": "user", "content": "Tail 0"},
            {"role": "assistant", "content": "Resp 0"},
        ]

        # UI shows 3 user turns, but only 1 survived in history: requesting a
        # rollback to the compacted region must clear history so the model
        # cannot remember rolled-back turns.
        agent.truncate_history_to_user_message(2)
        self.assertEqual(agent.history, [])

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
        self.assertIn("[Note: User attached image(s), but this model does not support vision.]", user_msg["content"])
        # Verify tool content was replaced with hint
        tool_msg = sanitized[2]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertIn(
            "[Hint: You do not support vision. Tell user you cannot view images. Do not retry.]", tool_msg["content"]
        )

    async def test_stream_cancelled_error_records_tokens(self):
        import asyncio

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


class TestAutoCompactionSysOverhead(unittest.IsolatedAsyncioTestCase):
    """The compaction threshold must count system prompt + tool schema overhead, not
    history alone — otherwise a large system prompt can overflow the context window
    before history ever reaches the 75% threshold."""

    async def test_compaction_triggers_when_sys_overhead_exceeds_threshold(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="s", tools=[])
        self.addAsyncCleanup(agent.close)
        agent.history = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
            {"role": "user", "content": "e"},
        ]

        def fake_estimate(val):
            if isinstance(val, str):
                return 100  # system prompt
            if isinstance(val, list):
                first = val[0] if val else None
                if isinstance(first, dict) and first.get("type") == "function":
                    return 0  # tools schema
                return 10  # history
            return 0

        with unittest.mock.patch("core.base_provider.agent.estimate_tokens", side_effect=fake_estimate):
            with unittest.mock.patch(
                "core.base_provider.BaseAgent.context_limit", new_callable=unittest.mock.PropertyMock
            ) as mock_limit:
                mock_limit.return_value = 100  # threshold = 75
                with unittest.mock.patch.object(
                    agent, "compact_history", new_callable=unittest.mock.AsyncMock
                ) as mock_comp:
                    mock_comp.return_value = (True, "compacted")
                    with unittest.mock.patch.object(
                        agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
                    ) as mock_create:
                        mock_create.side_effect = Exception("Stop stream")
                        try:
                            async for _ in agent.stream_steps("trigger"):
                                pass
                        except Exception:
                            pass
                        mock_comp.assert_called_once()


class TestRuntimeToolPolicy(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_blocks_write_aliases(self):
        from core.role_registry import AgentRole

        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="s", tools=[])
        self.addAsyncCleanup(agent.close)
        role_def = AgentRole("explorer", "Explorer", read_only=True, disallowed_tools=["write_file", "create", "edit"])
        err = agent._tool_policy_error("write_file", role_def)
        self.assertIsNotNone(err)
        self.assertTrue(err.is_error)
        self.assertIn("disabled in Explorer role", err.content)

    async def test_disallowed_tools_blocks_aliases(self):
        from core.role_registry import AgentRole

        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="s", tools=[])
        self.addAsyncCleanup(agent.close)
        role_def = AgentRole("locked", "Locked", disallowed_tools=["shell"])
        err = agent._tool_policy_error("shell", role_def)
        self.assertIsNotNone(err)
        self.assertIn("disabled in Locked role", err.content)


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


class TestBaseAgentStreamEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Unit tests for stream_steps() edge cases: MCP readiness, compaction,
    attachments, circuit breaker, adapter streams, retries, and error paths."""

    def _make_agent(self, **kwargs):
        defaults = dict(api_key="t", model="test-model", base_url="http://t", system_prompt="t", provider_key="tprov")
        defaults.update(kwargs)
        agent = BaseAgent(**defaults)
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

    async def test_auto_compaction_error_yields_warning(self):
        agent = self._make_agent()
        agent.history = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
            {"role": "user", "content": "e"},
        ]

        def fake_estimate(val):
            if isinstance(val, str):
                return 100
            if isinstance(val, list):
                first = val[0] if val else None
                if isinstance(first, dict) and first.get("type") == "function":
                    return 0
                return 10
            return 0

        with unittest.mock.patch("core.base_provider.agent.estimate_tokens", side_effect=fake_estimate):
            with unittest.mock.patch(
                "core.base_provider.BaseAgent.context_limit", new_callable=unittest.mock.PropertyMock
            ) as mock_limit:
                mock_limit.return_value = 100  # threshold = 75
                with unittest.mock.patch.object(
                    agent, "compact_history", new_callable=unittest.mock.AsyncMock
                ) as mock_comp:
                    mock_comp.side_effect = Exception("ctx overflow")
                    with unittest.mock.patch.object(
                        agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
                    ) as mock_create:
                        mock_create.side_effect = Exception("Stop stream")
                        events = []
                        try:
                            async for evt in agent.stream_steps("trigger"):
                                events.append(evt)
                        except Exception:
                            pass

        warnings = [e for e in events if e[0] == "thinking" and "Auto-compaction warning" in e[1]]
        self.assertEqual(len(warnings), 1)
        self.assertIn("ctx overflow", warnings[0][1])

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

    async def test_tool_policy_error_skips_execution(self):
        agent = self._make_agent()
        first = _MockStream([_tool_call_chunk(0, "tc_1", "shell", '{"command": "pwd"}')])
        second = _MockStream([_text_chunk("ok")])
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.side_effect = [first, second]
            agent.tool_executor = unittest.mock.AsyncMock()
            with unittest.mock.patch.object(
                agent,
                "_tool_policy_error",
                return_value=ToolResult.error("denied", name="shell", detail="blocked by policy"),
            ):
                events = []
                async for evt in agent.stream_steps("run shell"):
                    events.append(evt)

        self.assertIn(
            ("tool_result", "ERR: denied 'shell': blocked by policy", "", True, "error", None), events
        )
        agent.tool_executor.assert_not_called()
        self.assertEqual(events[-1], ("bot_text", "ok", ""))

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

    async def test_tool_image_json_string_display(self):
        agent = self._make_agent()
        results = [
            '{"type": "image", "path": "shot.png", "summary": "Screenshot"}',
            '{"type": "image", "path": "noshot.png"}',
            '{"type": "image", broken json',
        ]
        chunks = [
            _tool_call_chunk(0, "tc_0", "read", '{"path": "1.png"}'),
            _tool_call_chunk(1, "tc_1", "read", '{"path": "2.png"}'),
            _tool_call_chunk(2, "tc_2", "read", '{"path": "3.png"}'),
        ]
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.side_effect = [_MockStream(chunks), _MockStream([_text_chunk("ok")])]
            agent.tool_executor = unittest.mock.AsyncMock()
            agent.tool_executor.side_effect = results
            events = []
            async for evt in agent.stream_steps("show images"):
                events.append(evt)

        displays = [e[1] for e in events if e[0] == "tool_result"]
        self.assertEqual(displays, ["Screenshot", "[Image file: noshot.png]", results[2]])
        self.assertEqual(events[-1], ("bot_text", "ok", ""))

    async def test_tool_dict_and_none_results(self):
        agent = self._make_agent()
        chunks = [
            _tool_call_chunk(0, "tc_0", "read", '{"path": "1.png"}'),
            _tool_call_chunk(1, "tc_1", "read", '{"path": "2.txt"}'),
            _tool_call_chunk(2, "tc_2", "read", '{"path": "3.txt"}'),
        ]
        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.side_effect = [_MockStream(chunks), _MockStream([_text_chunk("ok")])]
            agent.tool_executor = unittest.mock.AsyncMock()
            agent.tool_executor.side_effect = [{"type": "image", "path": "y.png"}, {"a": 1}, None]
            events = []
            async for evt in agent.stream_steps("do stuff"):
                events.append(evt)

        displays = [e[1] for e in events if e[0] == "tool_result"]
        self.assertEqual(displays, ["[Image file: y.png]", {"a": 1}, None])
        tool_msgs = [m for m in agent.history if m.get("role") == "tool"]
        contents = [m["content"] for m in tool_msgs]
        self.assertEqual(contents, ['{"type": "image", "path": "y.png"}', '{"a": 1}', ""])

    async def test_compaction_in_loop_after_tool_turn(self):
        agent = self._make_agent()

        async def fake_compact(messages, sys_overhead, threshold):
            return (messages, True)

        first = _MockStream([_tool_call_chunk(0, "tc_1", "read", '{"path": "a.txt"}')])
        second = _MockStream([_text_chunk("ok")])
        with unittest.mock.patch.object(agent, "_compact_messages_if_needed", side_effect=fake_compact):
            with unittest.mock.patch.object(
                agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
            ) as mock_create:
                mock_create.side_effect = [first, second]
                agent.tool_executor = unittest.mock.AsyncMock(return_value="tool ok")
                events = []
                async for evt in agent.stream_steps("run tool"):
                    events.append(evt)

        notices = [e for e in events if e[0] == "thinking" and "Context budget reached" in e[1]]
        dividers = [e for e in events if e[0] == "event_divider" and e[1] == "Session Compacted"]
        self.assertEqual(len(notices), 1)
        self.assertEqual(len(dividers), 1)
        self.assertEqual(events[-1], ("bot_text", "ok", ""))


class TestDrainForeignSession(unittest.IsolatedAsyncioTestCase):
    async def test_drain_keeps_foreign_session_and_consumes_own(self):
        """Foreign-session messages must not cause an infinite loop and must stay queued."""
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        self.addAsyncCleanup(agent.close)

        app = unittest.mock.MagicMock()
        app.current_session_id = "sess_current"
        app.message_queue = [
            ("foreign", True, None, "sess_other"),
            ("own", True, None, "sess_current"),
            ("foreign2", True, None, "sess_other"),
        ]
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
        # Foreign-session messages left in the queue untouched.
        self.assertEqual([item[0] for item in app.message_queue], ["foreign", "foreign2"])

    async def test_drain_only_foreign_does_not_loop(self):
        """A queue containing only foreign-session messages must terminate."""
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        self.addAsyncCleanup(agent.close)

        app = unittest.mock.MagicMock()
        app.current_session_id = "sess_current"
        app.message_queue = [
            ("foreign", True, None, "sess_other"),
            ("foreign2", True, None, "sess_other"),
        ]
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


if __name__ == "__main__":
    unittest.main()
