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

    async def test_stream_tool_generating_to_running_lifecycle(self):
        tool_widget = MagicMock()
        tool_widget.status = "generating"
        tool_widget.update_tool_call = MagicMock()
        tool_widget.mark_running = MagicMock()
        tool_widget.set_result = MagicMock()
        self.chat_view.add_tool_call.return_value = tool_widget

        # 1. Model starts streaming tool call
        await self.driver.consume_stream_step(("tool_generating", "edit", "", {"id": "c1"}))
        self.chat_view.add_tool_call.assert_awaited_once_with("edit", "", args={}, status="generating")
        self.assertEqual(len(self.driver.tool_handles), 1)

        # 2. Target path streams in
        await self.driver.consume_stream_step(("tool_generating_update", "edit", "file.py", {"id": "c1"}))
        tool_widget.update_tool_call.assert_called_once_with(target="file.py")

        # 3. Generation finishes, execution starts
        await self.driver.consume_stream_step(("tool", "edit", "file.py", {"path": "file.py"}))
        tool_widget.mark_running.assert_called_once()
        self.assertEqual(self.chat_view.add_tool_call.await_count, 1)

        # 4. Result arrives
        await self.driver.consume_stream_step(("tool_result", "diff output", "", False, ToolResultStatus.DONE, 0))
        tool_widget.set_result.assert_called_once_with("diff output", is_error=False, status="done", returncode=0)
        self.assertEqual(len(self.driver.tool_handles), 0)

    async def test_stream_parallel_tools_generating_update_by_id(self):
        tw1 = MagicMock()
        tw1.status = "generating"
        tw1.update_tool_call = MagicMock()
        tw2 = MagicMock()
        tw2.status = "generating"
        tw2.update_tool_call = MagicMock()
        self.chat_view.add_tool_call.side_effect = [tw1, tw2]

        await self.driver.consume_stream_step(("tool_generating", "read", "", {"id": "c1", "index": 0}))
        await self.driver.consume_stream_step(("tool_generating", "read", "", {"id": "c2", "index": 1}))

        # Update for c2 should update tw2, not tw1
        await self.driver.consume_stream_step(("tool_generating_update", "read", "b.py", {"id": "c2", "index": 1}))
        tw2.update_tool_call.assert_called_once_with(target="b.py")
        tw1.update_tool_call.assert_not_called()

        # Update for c1 should update tw1
        await self.driver.consume_stream_step(("tool_generating_update", "read", "a.py", {"id": "c1", "index": 0}))
        tw1.update_tool_call.assert_called_once_with(target="a.py")

    async def test_stream_tool_matching_by_id_and_calls_on_tool_widget(self):
        tw1 = MagicMock()
        tw1.status = "generating"
        tw1.tool_call_id = "c1"
        tw1.update_tool_call = MagicMock()
        tw1.mark_running = MagicMock()

        tw2 = MagicMock()
        tw2.status = "generating"
        tw2.tool_call_id = "c2"
        tw2.update_tool_call = MagicMock()
        tw2.mark_running = MagicMock()

        self.chat_view.add_tool_call.side_effect = [tw1, tw2]
        tracked_widgets = []
        self.driver.on_tool_widget = lambda w: tracked_widgets.append(w)

        await self.driver.consume_stream_step(("tool_generating", "read", "", {"id": "c1", "index": 0}))
        await self.driver.consume_stream_step(("tool_generating", "read", "", {"id": "c2", "index": 1}))

        # Tool c2 runs first (e.g. concurrent or out-of-order)
        await self.driver.consume_stream_step(("tool", "read", "b.py", {"path": "b.py"}, "c2"))
        tw2.mark_running.assert_called_once()
        tw1.mark_running.assert_not_called()
        self.assertIn(tw2, tracked_widgets)

        # Result for c2 arrives first
        tw2.set_result = MagicMock()
        tw1.set_result = MagicMock()
        await self.driver.consume_stream_step(("tool_result", "content b", "", False, ToolResultStatus.DONE, 0, "c2"))
        tw2.set_result.assert_called_once_with("content b", is_error=False, status="done", returncode=0)
        tw1.set_result.assert_not_called()
        self.assertEqual(len(self.driver.tool_handles), 1)
        self.assertIn(tw1, self.driver.tool_handles)

    async def test_tool_generating_update_priority_two_pass(self):
        tw1 = MagicMock(status="generating", tool_call_id="c1", tool_call_index=0, update_tool_call=MagicMock())
        tw2 = MagicMock(status="generating", tool_call_id="c2", tool_call_index=0, update_tool_call=MagicMock())
        self.driver.tool_handles.extend([tw1, tw2])

        # Target c2 explicitly even if both share index 0
        await self.driver.consume_stream_step(("tool_generating_update", "read", "c2.py", {"id": "c2", "index": 0}))
        tw2.update_tool_call.assert_called_once_with(target="c2.py")
        tw1.update_tool_call.assert_not_called()

    async def test_stream_retry_cleans_up_generating_tool_widgets(self):
        tw = MagicMock()
        tw.status = "generating"
        tw.remove = MagicMock()
        self.driver.tool_handles.append(tw)

        await self.driver.consume_stream_step(("retry", 1, 3, 1.0, Exception("429")))
        tw.remove.assert_called_once()
        self.assertEqual(len(self.driver.tool_handles), 0)

    async def test_cleanup_unfinalized_tools(self):
        tw_gen = MagicMock()
        tw_gen.status = "generating"
        tw_gen.remove = MagicMock()

        tw_run = MagicMock()
        tw_run.status = "running"
        tw_run.set_result = MagicMock()

        self.driver.tool_handles.extend([tw_gen, tw_run])
        self.driver.cleanup_unfinalized_tools("Failed")

        tw_gen.remove.assert_called_once()
        tw_run.set_result.assert_called_once_with("Failed", is_error=True, status="error")

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

    async def test_session_event_completed_tool_empty_output_from_history(self):
        # Historical tool event with empty output (result_text="") must NOT be queued in tool_handles
        await self.driver.consume_session_event({
            "type": "tool",
            "tool_type": "shell",
            "target": "touch foo.txt",
            "result_text": "",
            "status": "done",
        })
        self.chat_view.add_tool_call.assert_awaited_once_with(
            "shell",
            "touch foo.txt",
            result_text="",
            args={},
            status="done",
            returncode=None,
            animate=True,
        )
        self.assertEqual(len(self.driver.tool_handles), 0)

    async def test_reset_clears_all_handles(self):
        self.driver.bot_handle = MagicMock()
        self.driver.thinking_handle = MagicMock()
        self.driver.tool_handles.append(MagicMock())

        self.driver.reset()
        self.assertIsNone(self.driver.bot_handle)
        self.assertIsNone(self.driver.thinking_handle)
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

    async def test_session_event_tool_generating_to_running_lifecycle(self):
        tool_widget = MagicMock()
        tool_widget.status = "generating"
        tool_widget.update_tool_call = MagicMock()
        tool_widget.mark_running = MagicMock()
        tool_widget.set_result = MagicMock()
        self.chat_view.add_tool_call.return_value = tool_widget

        # 1. tool_generating session event
        await self.driver.consume_session_event({
            "type": "tool_generating",
            "tool_type": "edit",
            "target": "",
            "meta": {"id": "c1"},
        })
        self.chat_view.add_tool_call.assert_awaited_once_with("edit", "", args={}, status="generating")
        self.assertEqual(len(self.driver.tool_handles), 1)

        # 2. tool_generating_update session event
        await self.driver.consume_session_event({
            "type": "tool_generating_update",
            "tool_type": "edit",
            "target": "file.py",
            "meta": {"id": "c1"},
        })
        tool_widget.update_tool_call.assert_called_once_with(target="file.py")

        # 3. Final tool event transitions generating to running
        await self.driver.consume_session_event({
            "type": "tool",
            "tool_type": "edit",
            "target": "file.py",
            "args": {"path": "file.py"},
            "tool_id": "c1",
        })
        tool_widget.mark_running.assert_called_once()
        self.assertEqual(self.chat_view.add_tool_call.await_count, 1)

        # 4. Result arrives
        await self.driver.consume_session_event({
            "type": "tool",
            "result_text": "diff output",
            "status": "done",
            "returncode": 0,
        })
        tool_widget.set_result.assert_called_once_with("diff output", is_error=False, status="done", returncode=0)
        self.assertEqual(len(self.driver.tool_handles), 0)

    async def test_session_event_tool_shell_output(self):
        tool_widget = MagicMock()
        tool_widget.status = "running"
        tool_widget.append_shell_output = MagicMock()
        self.driver.tool_handles.append(tool_widget)

        await self.driver.consume_session_event({
            "type": "tool_shell_output",
            "text": "building project...\n",
        })
        tool_widget.append_shell_output.assert_called_once_with("building project...\n")

    async def test_stream_informational_thinking_rendered(self):
        """Informational 'thinking' steps (auto-compaction notices) render as a
        finished thought block in the live path — matching history playback."""
        tw = MagicMock()
        tw.finish_thinking = MagicMock()
        self.chat_view.add_thinking_widget.return_value = tw

        await self.driver.consume_stream_step(("thinking", "Context budget reached; compacted.", ""))
        self.chat_view.add_thinking_widget.assert_awaited_once_with("Context budget reached; compacted.")
        tw.finish_thinking.assert_called_once()
        self.assertIsNone(self.driver.thinking_handle)

    async def test_stream_queued_user_message_ignored(self):
        """queued_user_message steps are rendered by the caller (ai_generator),
        never by the driver — the driver must not duplicate them."""
        await self.driver.consume_stream_step(("queued_user_message", "Follow-up", None, True, None))
        self.chat_view.add_user_message.assert_not_awaited()
        self.assertEqual(len(self.driver.tool_handles), 0)

    async def test_stream_unknown_step_ignored(self):
        """Events outside the canonical step protocol are no-ops."""
        await self.driver.consume_stream_step(("no_such_event", "x", "y"))
        self.chat_view.add_tool_call.assert_not_awaited()
        self.chat_view.add_bot_message.assert_not_awaited()
        self.chat_view.add_error_message.assert_not_awaited()

    async def test_stream_step_canonical_tool_result_carries_tool_id(self):
        """The canonical tool_result event keeps the tool_id so the session path
        can pair a result with its exact start event (id match before FIFO)."""
        w1 = MagicMock(status="running", tool_call_id="c1", set_result=MagicMock())
        w2 = MagicMock(status="running", tool_call_id="c2", set_result=MagicMock())
        self.driver.tool_handles.extend([w1, w2])

        await self.driver.consume_stream_step(
            ("tool_result", "content c2", "", False, ToolResultStatus.DONE, 0, "c2")
        )
        w2.set_result.assert_called_once_with("content c2", is_error=False, status="done", returncode=0)
        w1.set_result.assert_not_called()
        self.assertEqual(len(self.driver.tool_handles), 1)
        self.assertIn(w1, self.driver.tool_handles)

    async def test_session_event_tool_result_matches_by_id(self):
        w1 = MagicMock(status="running", tool_call_id="c1", set_result=MagicMock())
        w2 = MagicMock(status="running", tool_call_id="c2", set_result=MagicMock())
        self.driver.tool_handles.extend([w1, w2])

        await self.driver.consume_session_event({
            "type": "tool",
            "result_text": "content of c2",
            "status": "done",
            "tool_id": "c2",
        })
        w2.set_result.assert_called_once_with("content of c2", is_error=False, status="done", returncode=None)
        w1.set_result.assert_not_called()
        self.assertEqual(len(self.driver.tool_handles), 1)
        self.assertIn(w1, self.driver.tool_handles)

    async def test_session_event_retry_cleans_generating_keeps_running(self):
        tw_gen = MagicMock(status="generating", remove=MagicMock())
        tw_run = MagicMock(status="running", mark_cancelled=MagicMock())
        self.driver.tool_handles.extend([tw_run, tw_gen])

        await self.driver.consume_session_event({
            "type": "retry",
            "attempt": 2,
            "max_retries": 3,
            "delay": 1.0,
            "error": Exception("boom"),
        })
        tw_gen.remove.assert_called_once()
        # Running handles are pulled out of the FIFO (pending) so stale results
        # cannot misattach — they are finalized by status_change or reused.
        self.assertEqual(len(self.driver.tool_handles), 0)
        self.assertEqual(self.driver._pending_running_after_retry, [tw_run])
        self.assertNotIn(tw_run, self.driver.tool_handles)

    async def test_session_event_tool_shell_output_prefers_live_shell_card(self):
        done_card = MagicMock(status="done", append_shell_output=MagicMock())
        live_other = MagicMock(status="running", canonical_tool="read", append_shell_output=MagicMock())
        live_shell = MagicMock(status="running", canonical_tool="shell", append_shell_output=MagicMock())
        self.driver.tool_handles.extend([done_card, live_other, live_shell])

        await self.driver.consume_session_event({"type": "tool_shell_output", "text": "log line\n"})
        live_shell.append_shell_output.assert_called_once_with("log line\n")
        live_other.append_shell_output.assert_not_called()
        done_card.append_shell_output.assert_not_called()

    async def test_session_event_tool_shell_output_skips_completed_cards(self):
        done_last = MagicMock(status="done", append_shell_output=MagicMock())
        self.driver.tool_handles.append(done_last)

        await self.driver.consume_session_event({"type": "tool_shell_output", "text": "orphan\n"})
        done_last.append_shell_output.assert_not_called()

    def test_find_shell_output_target_child_fallback(self):
        from widgets.chat_toolcall import ToolCallWidget

        child = ToolCallWidget("shell", "tail -f log")
        child.status = "running"
        self.chat_view.children = [child]

        self.assertIs(self.driver._find_shell_output_target(), child)

    def test_match_tool_result_widget_unknown_id_falls_back_to_fifo(self):
        w1 = MagicMock(status="running", tool_call_id="c1")
        self.driver.tool_handles.append(w1)

        # Unmatched id still resolves via FIFO (queue order == announcement order).
        self.assertIs(self.driver._match_tool_result_widget({"tool_id": "unknown"}), w1)
        self.assertEqual(len(self.driver.tool_handles), 0)

    async def test_session_event_tool_result_child_fallback_by_id(self):
        from widgets.chat_toolcall import ToolCallWidget

        child = ToolCallWidget("shell", "run")
        child.status = "running"
        child.tool_call_id = "orphan-id"
        child.set_result = MagicMock()
        self.chat_view.children = [child]

        await self.driver.consume_session_event({
            "type": "tool",
            "result_text": "late result",
            "status": "done",
            "tool_id": "orphan-id",
        })
        child.set_result.assert_called_once_with("late result", is_error=False, status="done", returncode=None)

    async def test_tool_generating_update_matches_running_card(self):
        """A tool_generating_update landing after the card transitioned to
        running must still update that card instead of being dropped."""
        tw = MagicMock()
        tw.status = "running"
        tw.tool_call_id = "c1"
        tw.tool_call_index = 1
        tw.update_tool_call = MagicMock()
        self.driver.tool_handles.append(tw)

        await self.driver.consume_session_event({
            "type": "tool_generating_update",
            "tool_type": "edit",
            "target": "file.py",
            "meta": {"id": "c1", "index": 1},
        })
        tw.update_tool_call.assert_called_once_with(target="file.py")

        # Same via index matching with no id in the event.
        tw2 = MagicMock()
        tw2.status = "running"
        tw2.tool_call_index = 2
        tw2.update_tool_call = MagicMock()
        self.driver.tool_handles.append(tw2)
        await self.driver.consume_session_event({
            "type": "tool_generating_update",
            "tool_type": "edit",
            "target": "b.py",
            "meta": {"index": 2},
        })
        tw2.update_tool_call.assert_called_once_with(target="b.py")

    async def test_retry_running_handle_finalized_on_status_change(self):
        """A running card orphaned by a retry must be finalized (mark_cancelled,
        exactly once) when status_change('error') arrives, and the pending list
        must drain."""
        tw = MagicMock()
        tw.status = "running"
        tw.tool_call_id = "c1"
        tw.mark_cancelled = MagicMock()
        self.driver.tool_handles.append(tw)

        await self.driver.consume_session_event({
            "type": "retry",
            "attempt": 2,
            "max_retries": 3,
            "delay": 1.0,
            "error": Exception("boom"),
        })
        self.assertEqual(self.driver._pending_running_after_retry, [tw])
        self.assertEqual(len(self.driver.tool_handles), 0)
        self.assertEqual(tw.mark_cancelled.call_count, 0)

        await self.driver.consume_session_event({"type": "status_change", "status": "error"})
        tw.mark_cancelled.assert_called_once()
        self.assertEqual(self.driver._pending_running_after_retry, [])

    async def test_retry_running_handle_reused_by_reissued_tool(self):
        """When the retried turn re-issues the same tool, the mounted running
        card is reused (no duplicate widget) and re-marked running."""
        tw = MagicMock()
        tw.status = "running"
        tw.tool_call_id = "c1"
        tw.canonical_tool = "edit"
        tw.update_tool_call = MagicMock()
        tw.mark_running = MagicMock()
        self.driver.tool_handles.append(tw)
        self.chat_view.add_tool_call = AsyncMock()

        await self.driver.consume_session_event({
            "type": "retry",
            "attempt": 2,
            "max_retries": 3,
            "delay": 1.0,
            "error": Exception("boom"),
        })
        self.assertEqual(self.driver._pending_running_after_retry, [tw])

        await self.driver.consume_session_event({
            "type": "tool",
            "tool_type": "edit",
            "target": "file.py",
            "args": {"path": "file.py"},
            "tool_id": "c1",
        })
        self.chat_view.add_tool_call.assert_not_awaited()
        tw.update_tool_call.assert_called_once_with(target="file.py", args={"path": "file.py"})
        tw.mark_running.assert_called_once()
        self.assertEqual(self.driver._pending_running_after_retry, [])
        self.assertIn(tw, self.driver.tool_handles)

    async def test_retry_abandoned_running_handle_dropped_by_new_tool(self):
        """If the retried turn never re-calls the orphaned tool, a new tool
        event finalizes the abandoned card (mark_cancelled) and proceeds."""
        tw_abandoned = MagicMock()
        tw_abandoned.status = "running"
        tw_abandoned.tool_call_id = "old-c1"
        tw_abandoned.canonical_tool = "read"
        tw_abandoned.mark_cancelled = MagicMock()
        self.driver.tool_handles.append(tw_abandoned)

        await self.driver.consume_session_event({
            "type": "retry",
            "attempt": 2,
            "max_retries": 3,
            "delay": 1.0,
            "error": Exception("boom"),
        })
        self.assertEqual(self.driver._pending_running_after_retry, [tw_abandoned])

        new_widget = MagicMock()
        new_widget.status = "generating"
        self.chat_view.add_tool_call.return_value = new_widget

        await self.driver.consume_session_event({
            "type": "tool",
            "tool_type": "edit",
            "target": "file.py",
            "args": {"path": "file.py"},
        })
        tw_abandoned.mark_cancelled.assert_called_once()
        self.assertEqual(self.driver._pending_running_after_retry, [])
        self.chat_view.add_tool_call.assert_awaited_once_with(
            "edit", "file.py", args={"path": "file.py"}, result_text="", status=None, returncode=None, animate=True
        )
        self.assertIn(new_widget, self.driver.tool_handles)

    async def test_tool_result_matches_by_tool_type_widget(self):
        """Replay-path result events (tool_type present, no tool_id) must land
        on the live card of the same tool type, not on another running card."""
        w_edit = MagicMock(status="running", canonical_tool="edit", tool_type="edit", set_result=MagicMock())
        w_read = MagicMock(status="running", canonical_tool="read", tool_type="read", set_result=MagicMock())
        self.driver.tool_handles.extend([w_read, w_edit])

        await self.driver.consume_session_event({
            "type": "tool",
            "tool_type": "edit",
            "result_text": "r",
            "status": "done",
        })
        w_edit.set_result.assert_called_once_with("r", is_error=False, status="done", returncode=None)
        w_read.set_result.assert_not_called()
        self.assertEqual(len(self.driver.tool_handles), 1)
        self.assertIn(w_read, self.driver.tool_handles)
        self.assertNotIn(w_edit, self.driver.tool_handles)

