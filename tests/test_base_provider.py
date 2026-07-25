import os
import shutil
import tempfile
import unittest
import unittest.mock

from core.base_provider import BaseAgent
from tools.registry import execute_tool


class TestBaseProviderTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from tools.context import ToolContext
        ToolContext._instance = None
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        from tools.context import ToolContext
        ToolContext._instance = None
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

    async def test_bash_tool_sync(self):
        # Sync bash execution
        res_bash = await execute_tool("bash", {"command": "echo 'hello bash'"})
        self.assertEqual(res_bash.strip(), "hello bash")

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
        self.assertIn("<task_result>", res)
        self.assertIn("Subagent answer for: do research", res)

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
            {"role": "user", "content": [{"type": "text", "text": "Look at this"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,123"}}]},
            {"role": "assistant", "content": "Done", "tool_calls": [{"id": "call_1", "function": {"name": "read"}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "read", "content": "file contents"},
            {"role": "tool", "tool_call_id": "call_orphan", "name": "edit", "content": "orphan content"}
        ]

        sanitized = agent.sanitize_history_for_model(history)
        self.assertEqual(len(sanitized), 4)

        # Vision content transformed
        self.assertEqual(sanitized[0]["content"][1]["text"], "[Image attached (vision disabled for active model)]")

        # Valid tool output preserved
        self.assertEqual(sanitized[2]["role"], "tool")
        self.assertEqual(sanitized[2]["tool_call_id"], "call_1")

        # Orphan tool converted to user role
        self.assertEqual(sanitized[3]["role"], "user")
        self.assertIn("orphan content", sanitized[3]["content"])


if __name__ == "__main__":
    unittest.main()

