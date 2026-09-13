"""Coverage tests for ChatStreamDriver edge branches.

Covers exception guards, fallback matching paths, retry bookkeeping and
expand/content-finalization branches not exercised by the main driver tests.
"""
from unittest.mock import AsyncMock, MagicMock

from johnston.tui.presentation.widgets.chat_stream_driver import ChatStreamDriver
from johnston.tui.presentation.widgets.chat_toolcall import ToolCallWidget


def _make_driver():
    chat_view = MagicMock()
    chat_view.add_user_message = AsyncMock()
    chat_view.add_thinking_widget = AsyncMock()
    chat_view.add_tool_call = AsyncMock()
    chat_view.add_bot_message = AsyncMock()
    chat_view.add_error_message = AsyncMock()
    chat_view.add_event_divider = AsyncMock()
    return chat_view, ChatStreamDriver(chat_view)


async def test_finalize_thinking_remove_raises():
    _, driver = _make_driver()
    tw = MagicMock()
    tw.thinking_text = "   "
    tw.remove = MagicMock(side_effect=Exception("boom"))
    driver.thinking_handle = tw
    driver.finalize_thinking_stream()
    assert driver.thinking_handle is None


async def test_finalize_thinking_finish_raises():
    _, driver = _make_driver()
    tw = MagicMock()
    tw.thinking_text = "thought"
    tw.finish_thinking = MagicMock(side_effect=Exception("boom"))
    driver.thinking_handle = tw
    driver.finalize_thinking_stream(duration=1.0, content="")
    assert driver.thinking_handle is None


async def test_cleanup_generating_remove_and_cancel_raise():
    _, driver = _make_driver()
    th = MagicMock(status="generating")
    th.remove = MagicMock(side_effect=Exception("boom"))
    th.mark_cancelled = MagicMock(side_effect=Exception("boom"))
    driver.tool_handles.append(th)
    driver.cleanup_unfinalized_tools()
    assert len(driver.tool_handles) == 0


async def test_cleanup_running_result_raises():
    _, driver = _make_driver()
    th = MagicMock(status="running", set_result=MagicMock(side_effect=Exception("boom")))
    driver.tool_handles.append(th)
    driver.cleanup_unfinalized_tools("Failed")
    assert len(driver.tool_handles) == 0


async def test_cleanup_pending_running_after_retry_raises():
    _, driver = _make_driver()
    th = MagicMock(status="running", set_result=MagicMock(side_effect=Exception("boom")))
    driver._pending_running_after_retry.append(th)
    driver.cleanup_unfinalized_tools()
    assert driver._pending_running_after_retry == []


async def test_finalize_bot_flush_raises():
    _, driver = _make_driver()
    bm = MagicMock()
    bm.flush_pending_stream = MagicMock(side_effect=Exception("boom"))
    del bm._join_stream_content
    bm.content = "  "
    bm.remove = MagicMock()
    driver.bot_handle = bm
    await driver.finalize_bot_stream()
    bm.remove.assert_called_once()
    assert driver.bot_handle is None


async def test_finalize_bot_join_stream_raises():
    _, driver = _make_driver()
    bm = MagicMock()
    bm.flush_pending_stream = MagicMock()
    bm._join_stream_content = MagicMock(side_effect=Exception("boom"))
    bm.content = "joined fallback"
    bm.finalize_stream = MagicMock()
    driver.bot_handle = bm
    await driver.finalize_bot_stream()
    bm.finalize_stream.assert_called_once()
    assert driver.bot_handle is None


async def test_finalize_bot_remove_raises_and_awaitable_finalize():
    _, driver = _make_driver()
    bm = MagicMock()
    bm.flush_pending_stream = MagicMock()
    del bm._join_stream_content
    bm.content = "  "
    bm.remove = MagicMock(side_effect=Exception("boom"))
    driver.bot_handle = bm
    await driver.finalize_bot_stream()
    assert driver.bot_handle is None

    bm2 = MagicMock()
    bm2.flush_pending_stream = MagicMock()
    del bm2._join_stream_content
    bm2.content = "hello"
    bm2.finalize_stream = AsyncMock()
    driver.bot_handle = bm2
    await driver.finalize_bot_stream()
    bm2.finalize_stream.assert_awaited_once()
    assert driver.bot_handle is None


def test_match_tool_result_pops_finished_fifo_entries():
    _, driver = _make_driver()
    w_done = MagicMock(status="done")
    w_run = MagicMock(status="running")
    driver.tool_handles.extend([w_done, w_run])
    matched = driver._match_tool_result_widget({"result_text": "x"})
    assert matched is w_run
    assert len(driver.tool_handles) == 0


def test_match_tool_result_child_fallback_live_child():
    _, driver = _make_driver()
    child = ToolCallWidget("shell", "run")
    child.status = "running"
    child.set_result = MagicMock()
    driver.chat_view.children = [MagicMock(), child]
    matched = driver._match_tool_result_widget({"result_text": "x"})
    assert matched is child


def test_find_shell_output_target_by_task_id():
    _, driver = _make_driver()
    child = ToolCallWidget("shell", "run")
    child.background_task_id = "t1"
    driver.chat_view.children = [child]
    assert driver._find_shell_output_target("t1") is child

    th = MagicMock(task_id="t2")
    driver.tool_handles.append(th)
    assert driver._find_shell_output_target("t2") is th

    assert driver._find_shell_output_target("missing") is None


async def test_consume_session_event_non_dict_ignored():
    _, driver = _make_driver()
    await driver.consume_session_event("not-a-dict")
    driver.chat_view.add_user_message.assert_not_awaited()


async def test_consume_session_event_hidden_user_ignored():
    _, driver = _make_driver()
    await driver.consume_session_event({"type": "user", "text": "hidden", "show_in_ui": False})
    driver.chat_view.add_user_message.assert_not_awaited()


async def test_consume_session_event_user_attachments_count_from_list():
    _, driver = _make_driver()
    await driver.consume_session_event(
        {"type": "user", "text": "hi there", "attachments": ["a.png", "b.png"]}
    )
    driver.chat_view.add_user_message.assert_awaited_once_with(
        "hi there", animate=True, attachments_count=2
    )


async def test_thinking_from_stream_step_expanded():
    _, driver = _make_driver()
    tw = MagicMock()
    driver.chat_view.add_thinking_widget.return_value = tw
    await driver.consume_session_event(
        {"type": "thinking", "text": "t", "phase": "start", "from_stream_step": True},
        is_expanded=True,
    )
    driver.chat_view.add_thinking_widget.assert_awaited_once_with("t")
    assert tw.is_expanded is True


async def test_thinking_finalize_empty_remove_raises():
    _, driver = _make_driver()
    tw = MagicMock()
    tw.thinking_text = "   "
    tw.update_thinking = MagicMock()
    tw.remove = MagicMock(side_effect=Exception("boom"))
    driver.thinking_handle = tw
    await driver.consume_session_event(
        {"type": "thinking", "text": "", "duration": 1.0, "phase": "end"}
    )
    tw.remove.assert_called_once()
    assert driver.thinking_handle is None


async def test_tool_generating_update_no_ids_updates_first_generating():
    _, driver = _make_driver()
    th = MagicMock(status="generating", update_tool_call=MagicMock())
    driver.tool_handles.append(th)
    await driver.consume_session_event(
        {"type": "tool_generating_update", "tool_type": "edit", "target": "f.py", "meta": {}}
    )
    th.update_tool_call.assert_called_once_with(target="f.py")


async def test_tool_result_carries_background_task_and_log_path():
    _, driver = _make_driver()
    w = MagicMock(status="running", set_result=MagicMock())
    driver.tool_handles.append(w)
    await driver.consume_session_event(
        {
            "type": "tool",
            "result_text": "r",
            "status": "done",
            "background_task_id": "bg1",
            "log_path": "/tmp/j.log",
        }
    )
    w.set_result.assert_called_once_with(
        "r",
        is_error=False,
        status="done",
        returncode=None,
        background_task_id="bg1",
        log_path="/tmp/j.log",
    )


async def test_tool_event_matches_generating_handle_by_type():
    _, driver = _make_driver()
    th = MagicMock(status="generating", canonical_tool="edit")
    th.update_tool_call = MagicMock()
    th.mark_running = MagicMock()
    driver.tool_handles.append(th)
    await driver.consume_session_event({"type": "tool", "tool_type": "edit", "target": "f.py", "args": {}})
    th.update_tool_call.assert_called_once_with(target="f.py", args={})
    th.mark_running.assert_called_once()


async def test_tool_event_reuses_pending_running_handle_skipping_non_running():
    _, driver = _make_driver()
    w_done = MagicMock(status="done", tool_call_id="other", canonical_tool="read")
    w_run = MagicMock(status="running", tool_call_id="c1", canonical_tool="edit")
    w_run.update_tool_call = MagicMock()
    w_run.mark_running = MagicMock()
    driver._pending_running_after_retry.extend([w_done, w_run])
    await driver.consume_session_event(
        {"type": "tool", "tool_type": "edit", "target": "f.py", "args": {"p": 1}, "tool_id": "c1"}
    )
    assert driver._pending_running_after_retry == [w_done]
    assert w_run in driver.tool_handles
    w_run.update_tool_call.assert_called_once_with(target="f.py", args={"p": 1})
    w_run.mark_running.assert_called_once()


async def test_tool_event_abandoned_pending_cancel_raises_and_kwargs():
    _, driver = _make_driver()
    abandoned = MagicMock(status="running", tool_call_id="old", canonical_tool="read")
    abandoned.mark_cancelled = MagicMock(side_effect=Exception("boom"))
    driver._pending_running_after_retry.append(abandoned)
    widget = MagicMock()
    driver.chat_view.add_tool_call.return_value = widget
    await driver.consume_session_event(
        {
            "type": "tool",
            "tool_type": "edit",
            "target": "f.py",
            "args": {"p": 1},
            "tool_id": "new1",
            "background_task_id": "bg1",
            "subagent_session_id": "sub1",
            "log_path": "/tmp/l.log",
        }
    )
    driver.chat_view.add_tool_call.assert_awaited_once_with(
        "edit",
        "f.py",
        args={"p": 1},
        result_text="",
        status=None,
        returncode=None,
        animate=True,
        background_task_id="bg1",
        subagent_session_id="sub1",
        log_path="/tmp/l.log",
    )
    assert widget.tool_call_id == "new1"
    assert widget in driver.tool_handles


async def test_tool_event_is_expanded_set_expanded_method():
    _, driver = _make_driver()
    th = MagicMock(status="generating", canonical_tool="edit")
    th.update_tool_call = MagicMock()
    th.mark_running = MagicMock()
    th.is_expandable = MagicMock(return_value=True)
    th.set_expanded = MagicMock()
    driver.tool_handles.append(th)
    await driver.consume_session_event(
        {"type": "tool", "tool_type": "edit", "target": "f.py", "args": {}}, is_expanded=True
    )
    th.set_expanded.assert_called_once_with(True, scroll=False)


async def test_tool_event_is_expanded_fallback_attribute():
    _, driver = _make_driver()

    class _Target:
        is_expandable = staticmethod(lambda: True)
        is_expanded = False

    widget = _Target()
    driver.chat_view.add_tool_call.return_value = widget
    await driver.consume_session_event(
        {"type": "tool", "tool_type": "read", "target": "f.py", "args": {}, "from_stream_step": True},
        is_expanded=True,
    )
    assert widget.is_expanded is True


async def test_bot_empty_non_animate_non_active_returns():
    _, driver = _make_driver()
    await driver.consume_session_event({"type": "bot", "text": "   "}, animate=False, is_active=False)
    driver.chat_view.add_bot_message.assert_not_awaited()


async def test_bot_final_from_stream_step_set_final_content_awaited():
    _, driver = _make_driver()
    bm = MagicMock()
    bm.set_final_content = AsyncMock()
    del bm.finalize_stream
    driver.chat_view.add_bot_message.return_value = bm
    await driver.consume_session_event(
        {"type": "bot", "text": "done", "final": True, "from_stream_step": True}
    )
    bm.set_final_content.assert_awaited_once_with("done")
    assert driver.bot_handle is None


async def test_bot_final_session_event_finalize_stream_awaited():
    _, driver = _make_driver()
    bm = MagicMock()
    bm.finalize_stream = AsyncMock()
    del bm.set_final_content
    driver.chat_view.add_bot_message.return_value = bm
    await driver.consume_session_event({"type": "bot", "text": "done", "final": True})
    bm.finalize_stream.assert_awaited_once_with("done")
    assert driver.bot_handle is None


async def test_bot_reset_stream_raises():
    _, driver = _make_driver()
    bm = MagicMock()
    bm.reset_stream = MagicMock(side_effect=Exception("boom"))
    driver.bot_handle = bm
    await driver.consume_session_event({"type": "bot_reset"})
    assert driver.bot_handle is not None


async def test_retry_reset_stream_raises_and_notify_raises():
    _, driver = _make_driver()
    bm = MagicMock()
    bm.reset_stream = MagicMock(side_effect=Exception("boom"))
    driver.bot_handle = bm
    driver.notify = MagicMock(side_effect=Exception("boom"))
    await driver.consume_session_event(
        {"type": "retry", "attempt": 1, "max_retries": 3, "delay": 1.0, "error": Exception("rate limit")}
    )
    assert driver.bot_handle is not None


async def test_retry_remove_generating_raises_keeps_other_handles():
    _, driver = _make_driver()
    w_gen = MagicMock(status="generating", remove=MagicMock(side_effect=Exception("boom")))
    w_done = MagicMock(status="done")
    driver.tool_handles.extend([w_gen, w_done])
    await driver.consume_session_event(
        {"type": "retry", "attempt": 1, "max_retries": 3, "delay": 0.0, "error": None}
    )
    assert list(driver.tool_handles) == [w_done]


async def test_finalize_bot_uses_joined_stream_content():
    _, driver = _make_driver()
    bm = MagicMock()
    bm.flush_pending_stream = MagicMock()
    bm._join_stream_content.return_value = "joined deltas"
    bm.content = ""
    bm.finalize_stream = MagicMock()
    driver.bot_handle = bm
    await driver.finalize_bot_stream()
    bm.finalize_stream.assert_called_once()
    assert driver.bot_handle is None


async def test_thinking_session_event_adds_with_animate():
    _, driver = _make_driver()
    tw = MagicMock()
    driver.chat_view.add_thinking_widget.return_value = tw
    await driver.consume_session_event(
        {"type": "thinking", "text": "t", "phase": "start"}, animate=False, is_active=True
    )
    driver.chat_view.add_thinking_widget.assert_awaited_once_with("t", animate=False)
    assert driver.thinking_handle is tw


async def test_thinking_non_finite_duration_zeroed():
    import math

    _, driver = _make_driver()
    tw = MagicMock()
    tw.update_thinking = MagicMock()
    tw.finish_thinking = MagicMock()
    driver.thinking_handle = tw
    await driver.consume_session_event(
        {"type": "thinking", "text": "t", "duration": math.inf, "phase": "end"}
    )
    tw.finish_thinking.assert_called_once_with(0.0, "t")
    assert driver.thinking_handle is None


async def test_tool_result_orphan_logged_when_no_tool_type():
    _, driver = _make_driver()
    await driver.consume_session_event(
        {"type": "tool", "result_text": "orphan result", "status": "done"}
    )
    driver.chat_view.add_tool_call.assert_not_awaited()


async def test_bot_final_session_event_set_final_content_awaited():
    _, driver = _make_driver()
    bm = MagicMock()
    bm.set_final_content = AsyncMock()
    driver.chat_view.add_bot_message.return_value = bm
    await driver.consume_session_event({"type": "bot", "text": "done", "final": True})
    bm.set_final_content.assert_awaited_once_with("done")
    assert driver.bot_handle is None


async def test_bot_delta_set_stream_content_fallback():
    _, driver = _make_driver()
    bm = MagicMock()
    del bm.append_stream_content
    bm.set_stream_content = MagicMock()
    driver.chat_view.add_bot_message.return_value = bm
    await driver.consume_session_event({"type": "bot", "text": "x", "delta": "x"})
    bm.set_stream_content.assert_called_once_with("x")
    assert driver.bot_handle is bm


async def test_status_change_cancelled_cancels_queued_handles():
    _, driver = _make_driver()
    w = MagicMock(mark_cancelled=MagicMock())
    driver.tool_handles.append(w)
    await driver.consume_session_event({"type": "status_change", "status": "cancelled"})
    w.mark_cancelled.assert_called_once()
    assert len(driver.tool_handles) == 0


async def test_status_change_pending_cancel_raises():
    _, driver = _make_driver()
    w = MagicMock(status="running", mark_cancelled=MagicMock(side_effect=Exception("boom")))
    driver._pending_running_after_retry.append(w)
    await driver.consume_session_event({"type": "status_change", "status": "error"})
    assert driver._pending_running_after_retry == []
