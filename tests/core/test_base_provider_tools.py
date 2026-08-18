"""Tool-execution tests for core.base_provider (tools area).

Split out of the former test_base_provider monolith: real tool execution via
``execute_tool``, runtime tool-policy enforcement, and tool stream/results
display edge cases.
"""
import os
import shutil
import tempfile
import unittest
import unittest.mock

from core.base_provider import BaseAgent
from core.domain.defaults.errors import ToolResult
from core.role_registry import AgentRole
from tests.core._base_provider_helpers import _MockStream, _text_chunk, _tool_call_chunk, make_agent
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


class TestRuntimeToolPolicy(unittest.IsolatedAsyncioTestCase):
    async def test_disallowed_blocks_write_aliases(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="s", tools=[])
        self.addAsyncCleanup(agent.close)
        role_def = AgentRole("explorer", "Explorer", disallowed_tools=["write_file", "create", "edit"])
        err = agent._tool_policy_error("write_file", role_def)
        self.assertIsNotNone(err)
        self.assertTrue(err.is_error)
        self.assertIn("disabled in Explorer role", err.content)

    async def test_disallowed_tools_blocks_aliases(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="s", tools=[])
        self.addAsyncCleanup(agent.close)
        role_def = AgentRole("locked", "Locked", disallowed_tools=["shell"])
        err = agent._tool_policy_error("shell", role_def)
        self.assertIsNotNone(err)
        self.assertIn("disabled in Locked role", err.content)


class TestToolStreamEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Tool policy/display edge cases from the stream_steps path."""

    def _make_agent(self, **kwargs):
        agent = make_agent(**kwargs)
        self.addAsyncCleanup(agent.close)
        return agent

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
