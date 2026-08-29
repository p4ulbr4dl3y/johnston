"""Tests for concurrent tool execution and tool safety classification."""
import asyncio
import unittest
import unittest.mock
from typing import Any

from core.base_provider import BaseAgent
from core.domain.defaults.errors import ToolResult
from tools.ask_user import AskUserTool
from tools.base import BaseTool
from tools.create import CreateTool
from tools.edit import EditTool
from tools.invoke_subagent import InvokeSubagentTool
from tools.manage_shell import ManageShellTool
from tools.manage_subagent import ManageSubagentTool
from tools.read import ReadTool
from tools.registry import is_tool_concurrency_safe
from tools.shell import ShellTool
from tools.update_plan import UpdatePlanTool
from tools.web_fetch import WebFetchTool


class TestToolConcurrencySafety(unittest.TestCase):
    def test_default_base_tool_is_not_safe(self):
        tool = BaseTool()
        self.assertFalse(tool.is_concurrency_safe())

    def test_read_and_web_fetch_are_concurrency_safe(self):
        self.assertTrue(ReadTool().is_concurrency_safe())
        self.assertTrue(WebFetchTool().is_concurrency_safe())
        self.assertTrue(is_tool_concurrency_safe("read"))
        self.assertTrue(is_tool_concurrency_safe("web_fetch"))

    def test_mutating_and_interactive_tools_are_not_concurrency_safe(self):
        self.assertFalse(CreateTool().is_concurrency_safe())
        self.assertFalse(EditTool().is_concurrency_safe())
        self.assertFalse(ShellTool().is_concurrency_safe())
        self.assertFalse(AskUserTool().is_concurrency_safe())
        self.assertFalse(ManageShellTool().is_concurrency_safe())
        self.assertFalse(InvokeSubagentTool().is_concurrency_safe())
        self.assertFalse(ManageSubagentTool().is_concurrency_safe())
        self.assertFalse(UpdatePlanTool().is_concurrency_safe())

        self.assertFalse(is_tool_concurrency_safe("create"))
        self.assertFalse(is_tool_concurrency_safe("edit"))
        self.assertFalse(is_tool_concurrency_safe("shell"))
        self.assertFalse(is_tool_concurrency_safe("ask_user"))
        self.assertFalse(is_tool_concurrency_safe("unknown_tool_xyz"))


class TestConcurrentToolExecutionInAgent(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_read_tools_run_in_parallel(self):
        agent = BaseAgent(
            api_key="test",
            model="test-model",
            base_url="http://test",
            system_prompt="test",
            provider_key="test",
        )
        self.addAsyncCleanup(agent.close)

        running_count = 0
        max_concurrent = 0

        async def mock_executor(name: str, args: dict, agent_ref: Any = None):
            nonlocal running_count, max_concurrent
            running_count += 1
            max_concurrent = max(max_concurrent, running_count)
            await asyncio.sleep(0.05)
            running_count -= 1
            return ToolResult(content=f"Result for {args.get('path')}")

        agent.tool_executor = mock_executor

        turn_num = 0

        class MockAdapter:
            async def stream_chat(self, **kwargs):
                nonlocal turn_num
                turn_num += 1
                if turn_num == 1:
                    yield ("adapter_tool_call", {"id": "call_1", "name": "read", "arguments": '{"path": "f1.txt"}'})
                    yield ("adapter_tool_call", {"id": "call_2", "name": "read", "arguments": '{"path": "f2.txt"}'})
                    yield ("adapter_tool_call", {"id": "call_3", "name": "read", "arguments": '{"path": "f3.txt"}'})
                else:
                    yield ("adapter_text", "All files read")

        events = []
        with unittest.mock.patch("core.adapters.get_adapter", return_value=MockAdapter()):
            async for ev in agent.stream_steps("Read 3 files"):
                events.append(ev)

        # Verify concurrency occurred (all 3 ran concurrently)
        self.assertEqual(max_concurrent, 3)

        # Verify tool calls and results were emitted in correct order
        tool_events = [ev for ev in events if ev[0] == "tool"]
        self.assertEqual(len(tool_events), 3)
        self.assertEqual(tool_events[0][1], "read")
        self.assertEqual(tool_events[0][2], "f1.txt")
        self.assertEqual(tool_events[1][2], "f2.txt")
        self.assertEqual(tool_events[2][2], "f3.txt")

        result_events = [ev for ev in events if ev[0] == "tool_result"]
        self.assertEqual(len(result_events), 3)
        self.assertIn("f1.txt", str(result_events[0][1]))
        self.assertIn("f2.txt", str(result_events[1][1]))
        self.assertIn("f3.txt", str(result_events[2][1]))

    async def test_mixed_tools_preserve_barrier_and_ordering(self):
        agent = BaseAgent(
            api_key="test",
            model="test-model",
            base_url="http://test",
            system_prompt="test",
            provider_key="test",
        )
        self.addAsyncCleanup(agent.close)

        execution_log = []

        async def mock_executor(name: str, args: dict, agent_ref: Any = None):
            execution_log.append((name, args.get("target") or args.get("path") or args.get("command")))
            await asyncio.sleep(0.01)
            return ToolResult(content=f"Done {name}")

        agent.tool_executor = mock_executor

        turn_num = 0

        class MockAdapter:
            async def stream_chat(self, **kwargs):
                nonlocal turn_num
                turn_num += 1
                if turn_num == 1:
                    # Emits: read1, read2, shell (barrier), read3
                    yield ("adapter_tool_call", {"id": "call_1", "name": "read", "arguments": '{"path": "a.py"}'})
                    yield ("adapter_tool_call", {"id": "call_2", "name": "read", "arguments": '{"path": "b.py"}'})
                    yield ("adapter_tool_call", {"id": "call_3", "name": "shell", "arguments": '{"command": "echo hi"}'})
                    yield ("adapter_tool_call", {"id": "call_4", "name": "read", "arguments": '{"path": "c.py"}'})
                else:
                    yield ("adapter_text", "Done")

        events = []
        with unittest.mock.patch("core.adapters.get_adapter", return_value=MockAdapter()):
            async for ev in agent.stream_steps("Mixed tools"):
                events.append(ev)

        # Verify execution order: a.py & b.py ran first, then shell, then c.py
        self.assertEqual(len(execution_log), 4)
        self.assertEqual(execution_log[0][0], "read")
        self.assertEqual(execution_log[1][0], "read")
        self.assertEqual(execution_log[2][0], "shell")
        self.assertEqual(execution_log[3][0], "read")
        self.assertEqual(execution_log[3][1], "c.py")

        # Verify message history contains tool results in exact 1..4 order
        tool_messages = [m for m in agent.history if m.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 4)
        self.assertEqual(tool_messages[0]["tool_call_id"], "call_1")
        self.assertEqual(tool_messages[1]["tool_call_id"], "call_2")
        self.assertEqual(tool_messages[2]["tool_call_id"], "call_3")
        self.assertEqual(tool_messages[3]["tool_call_id"], "call_4")

    async def test_concurrent_tool_error_handling(self):
        agent = BaseAgent(
            api_key="test",
            model="test-model",
            base_url="http://test",
            system_prompt="test",
            provider_key="test",
        )
        self.addAsyncCleanup(agent.close)

        async def mock_executor(name: str, args: dict, agent_ref: Any = None):
            if args.get("path") == "f2_error.txt":
                raise RuntimeError("File unreadable")
            return ToolResult(content=f"Content of {args.get('path')}")

        agent.tool_executor = mock_executor

        turn_num = 0

        class MockAdapter:
            async def stream_chat(self, **kwargs):
                nonlocal turn_num
                turn_num += 1
                if turn_num == 1:
                    yield ("adapter_tool_call", {"id": "c1", "name": "read", "arguments": '{"path": "f1.txt"}'})
                    yield ("adapter_tool_call", {"id": "c2", "name": "read", "arguments": '{"path": "f2_error.txt"}'})
                    yield ("adapter_tool_call", {"id": "c3", "name": "read", "arguments": '{"path": "f3.txt"}'})
                else:
                    yield ("adapter_text", "Done")

        events = []
        with unittest.mock.patch("core.adapters.get_adapter", return_value=MockAdapter()):
            async for ev in agent.stream_steps("Read files"):
                events.append(ev)

        result_events = [ev for ev in events if ev[0] == "tool_result"]
        self.assertEqual(len(result_events), 3)
        self.assertIn("Content of f1.txt", str(result_events[0][1]))
        self.assertTrue(result_events[1][3])  # is_error is True
        self.assertIn("Content of f3.txt", str(result_events[2][1]))

        tool_messages = [m for m in agent.history if m.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 3)
        self.assertEqual(tool_messages[0]["tool_call_id"], "c1")
        self.assertEqual(tool_messages[1]["tool_call_id"], "c2")
        self.assertEqual(tool_messages[2]["tool_call_id"], "c3")


class TestConcurrentToolsGeneratorAndSession(unittest.IsolatedAsyncioTestCase):
    async def test_ai_generator_concurrent_tool_ui_handles(self):
        from core.application.generation.ai_generator import GenCanvas, generate_ai_response
        from core.domain.entities.session import AgentSession

        w1, w2, w3 = unittest.mock.MagicMock(), unittest.mock.MagicMock(), unittest.mock.MagicMock()
        widgets = [w1, w2, w3]

        async def fake_add_tool_call(name, target, args=None):
            return widgets.pop(0)

        canvas = GenCanvas(
            add_user_message=unittest.mock.AsyncMock(),
            add_thinking_widget=unittest.mock.AsyncMock(return_value=unittest.mock.MagicMock()),
            add_tool_call=unittest.mock.AsyncMock(side_effect=fake_add_tool_call),
            add_bot_message=unittest.mock.AsyncMock(
                return_value=unittest.mock.MagicMock(
                    content="",
                    finalize_stream=unittest.mock.AsyncMock(),
                    reset_stream=unittest.mock.AsyncMock(),
                    flush_pending_stream=unittest.mock.MagicMock(),
                )
            ),
            add_event_divider=unittest.mock.AsyncMock(),
            get_user_messages=unittest.mock.MagicMock(return_value=[("0", "hi")]),
            refresh_status_footer=unittest.mock.MagicMock(),
            notify=unittest.mock.MagicMock(),
            save_session=unittest.mock.AsyncMock(),
        )

        class FakeAgent:
            def __init__(self):
                self.history = []
                self._last_sys_tokens = 0
                self.last_context_tokens = 0
                self.model = "gpt-4o"

            async def stream_steps(self, prompt, attachments=None):
                yield ("tool", "read", "f1.txt", {"path": "f1.txt"})
                yield ("tool", "read", "f2.txt", {"path": "f2.txt"})
                yield ("tool", "read", "f3.txt", {"path": "f3.txt"})
                yield ("tool_result", "res1", "", False, None, None)
                yield ("tool_result", "res2", "", False, None, None)
                yield ("tool_result", "res3", "", False, None, None)
                yield ("bot_text", "done")

        session = AgentSession("test_sess", prompt="test prompt")
        agent = FakeAgent()
        await generate_ai_response(agent, session, canvas, session_id="test_sess", user_text="Read files")

        w1.set_result.assert_called_once()
        self.assertEqual(w1.set_result.call_args[0][0], "res1")
        w2.set_result.assert_called_once()
        self.assertEqual(w2.set_result.call_args[0][0], "res2")
        w3.set_result.assert_called_once()
        self.assertEqual(w3.set_result.call_args[0][0], "res3")

    async def test_ai_generator_concurrent_tool_interruption(self):
        from core.application.generation.ai_generator import GenCanvas, generate_ai_response
        from core.domain.entities.session import AgentSession

        w1, w2 = unittest.mock.MagicMock(), unittest.mock.MagicMock()
        widgets = [w1, w2]

        async def fake_add_tool_call(name, target, args=None):
            return widgets.pop(0)

        canvas = GenCanvas(
            add_user_message=unittest.mock.AsyncMock(),
            add_thinking_widget=unittest.mock.AsyncMock(return_value=unittest.mock.MagicMock()),
            add_tool_call=unittest.mock.AsyncMock(side_effect=fake_add_tool_call),
            add_bot_message=unittest.mock.AsyncMock(
                return_value=unittest.mock.MagicMock(
                    content="",
                    finalize_stream=unittest.mock.AsyncMock(),
                    reset_stream=unittest.mock.AsyncMock(),
                    flush_pending_stream=unittest.mock.MagicMock(),
                )
            ),
            add_event_divider=unittest.mock.AsyncMock(),
            get_user_messages=unittest.mock.MagicMock(return_value=[("0", "hi")]),
            refresh_status_footer=unittest.mock.MagicMock(),
            notify=unittest.mock.MagicMock(),
            save_session=unittest.mock.AsyncMock(),
        )

        class FakeAgent:
            def __init__(self):
                self.history = []
                self._last_sys_tokens = 0
                self.last_context_tokens = 0
                self.model = "gpt-4o"

            async def stream_steps(self, prompt, attachments=None):
                yield ("tool", "read", "f1.txt", {"path": "f1.txt"})
                yield ("tool", "read", "f2.txt", {"path": "f2.txt"})
                raise asyncio.CancelledError

        session = AgentSession("test_sess", prompt="test prompt")
        agent = FakeAgent()
        with self.assertRaises(asyncio.CancelledError):
            await generate_ai_response(agent, session, canvas, session_id="test_sess", user_text="Read files")

        w1.mark_cancelled.assert_called_once()
        w2.mark_cancelled.assert_called_once()

    def test_session_add_event_concurrent_batch_tools(self):
        from core.domain.entities.session import AgentSession

        sess = AgentSession("s_batch", prompt="test")
        sess.add_event({"type": "tool", "tool_type": "read", "target": "1.py", "args": {"path": "1.py"}})
        sess.add_event({"type": "tool", "tool_type": "read", "target": "2.py", "args": {"path": "2.py"}})
        sess.add_event({"type": "tool", "tool_type": "read", "target": "3.py", "args": {"path": "3.py"}})

        sess.add_event({"type": "tool", "result_text": "content_1", "status": "done"})
        sess.add_event({"type": "tool", "result_text": "content_2", "status": "done"})
        sess.add_event({"type": "tool", "result_text": "content_3", "status": "done"})

        tool_msgs = [m for m in sess.messages if m.get("type") == "tool"]
        self.assertEqual(len(tool_msgs), 3)
        self.assertEqual(tool_msgs[0]["target"], "1.py")
        self.assertEqual(tool_msgs[0]["result_text"], "content_1")
        self.assertEqual(tool_msgs[1]["target"], "2.py")
        self.assertEqual(tool_msgs[1]["result_text"], "content_2")
        self.assertEqual(tool_msgs[2]["target"], "3.py")
        self.assertEqual(tool_msgs[2]["result_text"], "content_3")

