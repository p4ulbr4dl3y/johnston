"""Unit tests for ChatStreamDriver."""
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.domain.defaults.errors import ToolResultStatus
from widgets.presentation.widgets.chat_stream_driver import ChatStreamDriver


class TestChatStreamDriver(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.chat_view = MagicMock()
        self.chat_view.add_user_message = AsyncMock()
        self.chat_view.add_thinking_widget = AsyncMock()
        self.chat_view.add_tool_call = AsyncMock()
        self.chat_view.add_bot_message = AsyncMock()
        self.chat_view.add_error_message = AsyncMock()
        self.chat_view.add_event_divider = AsyncMock()
        self.driver = ChatStreamDriver(self.chat_view)

    async def test_stream_thinking_lifecycle(self):
        tw = MagicMock()
        tw.update_thinking = MagicMock()
        tw.finish_thinking = MagicMock()
        self.chat_view.add_thinking_widget.return_value = tw

        await self.driver.consume_stream_step(("thinking_start", "Thinking...", ""))
        self.chat_view.add_thinking_widget.assert_awaited_once_with("Thinking...")
        self.assertEqual(self.driver.thinking_handle, tw)

        await self.driver.consume_stream_step(("thinking_delta", "Step 1", ""))
        tw.update_thinking.assert_called_once_with("Step 1")

        await self.driver.consume_stream_step(("thinking_end", "1.5", "Done thought"))
        tw.finish_thinking.assert_called_once_with(1.5, "Done thought")
        self.assertIsNone(self.driver.thinking_handle)

    async def test_stream_tool_and_result_lifecycle(self):
        tool_widget = MagicMock()
        tool_widget.set_result = MagicMock()
        self.chat_view.add_tool_call.return_value = tool_widget

        registered_tools = []
        self.driver.on_tool_widget = lambda w: registered_tools.append(w)

        # 1. Tool call starts
        await self.driver.consume_stream_step(("tool", "edit", "file.py", {"path": "file.py"}))
        self.chat_view.add_tool_call.assert_awaited_once_with("edit", "file.py", args={"path": "file.py"})
        self.assertEqual(len(self.driver.tool_handles), 1)
        self.assertEqual(registered_tools, [tool_widget])

        # 2. Tool result arrives
        await self.driver.consume_stream_step(("tool_result", "diff content", "", False, ToolResultStatus.DONE, 0))
        self.assertEqual(len(self.driver.tool_handles), 0)
        tool_widget.set_result.assert_called_once_with("diff content", is_error=False, status="done", returncode=0)

    async def test_stream_multiple_tools_fifo_order(self):
        tw1 = MagicMock()
        tw2 = MagicMock()
        self.chat_view.add_tool_call.side_effect = [tw1, tw2]

        await self.driver.consume_stream_step(("tool", "read", "a.txt", {"path": "a.txt"}))
        await self.driver.consume_stream_step(("tool", "read", "b.txt", {"path": "b.txt"}))
        self.assertEqual(len(self.driver.tool_handles), 2)

        await self.driver.consume_stream_step(("tool_result", "content A", "", False, ToolResultStatus.DONE, None))
        tw1.set_result.assert_called_once_with("content A", is_error=False, status="done", returncode=None)
        tw2.set_result.assert_not_called()

        await self.driver.consume_stream_step(("tool_result", "content B", "", False, ToolResultStatus.DONE, None))
        tw2.set_result.assert_called_once_with("content B", is_error=False, status="done", returncode=None)
        self.assertEqual(len(self.driver.tool_handles), 0)

    async def test_stream_bot_delta_and_finalize(self):
        bm = MagicMock()
        bm.append_stream_content = MagicMock()
        bm.finalize_stream = AsyncMock()
        self.chat_view.add_bot_message.return_value = bm

        await self.driver.consume_stream_step(("bot_delta", "Hello ", ""))
        self.chat_view.add_bot_message.assert_awaited_once()
        bm.append_stream_content.assert_called_once_with("Hello ")

        await self.driver.consume_stream_step(("bot_text", "Hello world", ""))
        bm.finalize_stream.assert_awaited_once_with("Hello world")
        self.assertIsNone(self.driver.bot_handle)

    async def test_stream_bot_reset_and_retry_notification(self):
        bm = MagicMock()
        bm.reset_stream = AsyncMock()
        self.driver.bot_handle = bm

        notifications = []
        self.driver.notify = lambda msg, severity=None: notifications.append((msg, severity))

        await self.driver.consume_stream_step(("bot_reset", "", ""))
        bm.reset_stream.assert_awaited_once()

        await self.driver.consume_stream_step(("retry", 1, 3, 2.0, Exception("rate limit 429")))
        self.assertEqual(len(notifications), 1)
        self.assertIn("Rate limit reached: retrying in 2s", notifications[0][0])
        self.assertEqual(notifications[0][1], "warning")

    async def test_stream_error_and_event_divider(self):
        await self.driver.consume_stream_step(("error", "Something broke", ""))
        self.chat_view.add_error_message.assert_awaited_once_with("Something broke")

        await self.driver.consume_stream_step(("event_divider", "Turn Compacted", ""))
        self.chat_view.add_event_divider.assert_awaited_once_with("Turn Compacted")

    async def test_finalize_bot_stream_removes_empty(self):
        bm = MagicMock()
        bm.content = "   "
        bm._stream_parts = []
        bm.remove = MagicMock()
        self.driver.bot_handle = bm

        await self.driver.finalize_bot_stream()
        bm.remove.assert_called_once()
        self.assertIsNone(self.driver.bot_handle)

    async def test_session_event_tool_start_and_result(self):
        tool_widget = MagicMock()
        self.chat_view.add_tool_call.return_value = tool_widget

        # Live tool start (no result_text)
        await self.driver.consume_session_event({
            "type": "tool",
            "tool_type": "edit",
            "target": "foo.py",
            "args": {"path": "foo.py"},
        })
        self.assertEqual(len(self.driver.tool_handles), 1)

        # Tool result event (result_text without tool_type)
        await self.driver.consume_session_event({
            "type": "tool",
            "result_text": "patch applied",
            "status": "done",
            "returncode": 0,
        })
        self.assertEqual(len(self.driver.tool_handles), 0)
        tool_widget.set_result.assert_called_once_with("patch applied", is_error=False, status="done", returncode=0)

    async def test_session_event_completed_tool_from_history(self):
        # Historical completed tool event (has both tool_type and result_text)
        await self.driver.consume_session_event({
            "type": "tool",
            "tool_type": "read",
            "target": "readme.md",
            "result_text": "# Title",
            "status": "done",
        })
        self.chat_view.add_tool_call.assert_awaited_once_with(
            "read",
            "readme.md",
            result_text="# Title",
            args={},
            status="done",
            returncode=None,
            animate=True,
        )
        # Completed history event must NOT be queued in tool_handles
        self.assertEqual(len(self.driver.tool_handles), 0)

    async def test_session_event_plan_update_callback(self):
        plans = []
        self.driver.on_plan_update = lambda p, exp: plans.append((p, exp))

        await self.driver.consume_session_event({
            "type": "tool",
            "tool_type": "update_plan",
            "target": "plan",
            "args": {"plan": [{"step": "A", "status": "in_progress"}], "explanation": "test"},
            "result_text": "plan set",
        })
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0][0], [{"step": "A", "status": "in_progress"}])
        self.assertEqual(plans[0][1], "test")
