"""Comprehensive test suite for interruption and cancellation handling across Johnston.

Covers:
1. `_handle_interruption` in core/application/generation/ai_generator.py (thinking, bot, tool, tokens, session, canvas)
2. History sanitization and compaction of interrupted states (synthetic tool results, system notes)
3. UI Escape key routing in ChatInput (suggestions vs worker cancellation)
4. ToolCallWidget widget cancellation states and UI rendering
5. Session manager visibility and rewind with interruption notes
6. Full stream generator cancellation lifecycle
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.events import Key

from core.application.generation.ai_generator import (
    GenCanvas,
    _handle_interruption,
    generate_ai_response,
)
from core.base_provider import BaseAgent
from core.base_provider.compaction import collect_user_messages
from core.domain.entities.session import AgentSession
from core.domain.policies.messages import is_system_note, is_ui_visible_user_message
from widgets.chat_input import KEY_QUIT, ChatInput
from widgets.chat_toolcall import ToolCallWidget


def _make_canvas(**overrides) -> GenCanvas:
    c = GenCanvas(
        add_user_message=AsyncMock(),
        add_thinking_widget=AsyncMock(return_value=MagicMock(is_thinking=True)),
        add_tool_call=AsyncMock(return_value=MagicMock()),
        add_bot_message=AsyncMock(
            return_value=MagicMock(
                content="", finalize_stream=AsyncMock(), reset_stream=AsyncMock(), flush_pending_stream=MagicMock()
            )
        ),
        add_event_divider=AsyncMock(),
        get_user_messages=MagicMock(return_value=[("0", "hi")]),
        refresh_status_footer=MagicMock(),
        notify=MagicMock(),
        save_session=AsyncMock(),
    )
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


# ============================================================================
# 1. Direct _handle_interruption Unit Tests
# ============================================================================


class TestHandleInterruption:
    """Tests for _handle_interruption ensuring all partial states are cleaned up."""

    @pytest.mark.asyncio
    async def test_interruption_finishes_active_thinking(self):
        thinking_handle = MagicMock()
        thinking_handle.is_thinking = True
        thinking_handle.finish_thinking = MagicMock()

        canvas = _make_canvas()
        start_time = time.time() - 2.5

        await _handle_interruption(
            agent=MagicMock(),
            session=None,
            canvas=canvas,
            thinking_handle=thinking_handle,
            bot_handle=None,
            tool_handle=None,
            start_time=start_time,
        )

        thinking_handle.finish_thinking.assert_called_once()
        duration_arg = thinking_handle.finish_thinking.call_args[0][0]
        assert duration_arg >= 2.0

    @pytest.mark.asyncio
    async def test_interruption_finalizes_partial_bot_reply_and_appends_system_note(self):
        bot_handle = MagicMock()
        bot_handle.content = "Partial generated response from LLM"
        bot_handle.finalize_stream = AsyncMock()

        agent = MagicMock()
        agent.history = [{"role": "user", "content": "Hello"}]
        agent._last_sys_tokens = 50

        canvas = _make_canvas()

        session = MagicMock()
        session.add_event = MagicMock()

        await _handle_interruption(
            agent=agent,
            session=session,
            canvas=canvas,
            thinking_handle=None,
            bot_handle=bot_handle,
            tool_handle=None,
            start_time=time.time(),
        )

        bot_handle.finalize_stream.assert_awaited_once()

        # Check history contains partial response + interruption note
        assert len(agent.history) == 3
        assert agent.history[1] == {"role": "assistant", "content": "Partial generated response from LLM"}
        assert agent.history[2] == {
            "role": "user",
            "content": "<system_note>Interrupted</system_note>",
        }

        # Token accounting and UI refresh
        assert hasattr(agent, "last_context_tokens")
        assert agent.last_context_tokens > 50
        canvas.refresh_status_footer.assert_called_once()

        # Session and canvas dividers
        session.add_event.assert_called_once_with({"type": "event_divider", "text": "Response Interrupted"})
        canvas.add_event_divider.assert_awaited_once_with("Response Interrupted")

    @pytest.mark.asyncio
    async def test_interruption_with_empty_bot_content_removes_widget_and_no_assistant_turn(self):
        bot_handle = MagicMock()
        bot_handle.content = "   \n "
        bot_handle.finalize_stream = AsyncMock()

        agent = MagicMock()
        agent.history = [{"role": "user", "content": "Hello"}]
        agent._last_sys_tokens = 10

        canvas = _make_canvas()

        await _handle_interruption(
            agent=agent,
            session=None,
            canvas=canvas,
            thinking_handle=None,
            bot_handle=bot_handle,
            tool_handle=None,
            start_time=time.time(),
        )

        bot_handle.finalize_stream.assert_not_called()
        # History should NOT have an empty assistant turn, only the system note
        assert len(agent.history) == 2
        assert agent.history[0] == {"role": "user", "content": "Hello"}
        assert agent.history[1] == {
            "role": "user",
            "content": "<system_note>Interrupted</system_note>",
        }

    @pytest.mark.asyncio
    async def test_interruption_marks_inflight_tool_as_cancelled(self):
        tool_handle = MagicMock()
        tool_handle.mark_cancelled = MagicMock()

        canvas = _make_canvas()

        await _handle_interruption(
            agent=MagicMock(history=[]),
            session=None,
            canvas=canvas,
            thinking_handle=None,
            bot_handle=None,
            tool_handle=tool_handle,
            start_time=time.time(),
        )

        tool_handle.mark_cancelled.assert_called_once()

    @pytest.mark.asyncio
    async def test_interruption_catches_and_swallows_all_component_failures(self):
        thinking_handle = MagicMock()
        thinking_handle.finish_thinking.side_effect = RuntimeError("thinking error")

        bot_handle = MagicMock()
        bot_handle.content = "partial"
        bot_handle.finalize_stream = AsyncMock(side_effect=RuntimeError("stream finalize error"))

        tool_handle = MagicMock()
        tool_handle.mark_cancelled.side_effect = RuntimeError("tool cancel error")

        canvas = _make_canvas(
            add_event_divider=AsyncMock(side_effect=RuntimeError("canvas error")),
            refresh_status_footer=MagicMock(side_effect=RuntimeError("footer error")),
        )

        session = MagicMock()
        session.add_event.side_effect = RuntimeError("session error")

        agent = MagicMock()
        agent.history = []

        # Must not raise despite all sub-call failures
        await _handle_interruption(
            agent=agent,
            session=session,
            canvas=canvas,
            thinking_handle=thinking_handle,
            bot_handle=bot_handle,
            tool_handle=tool_handle,
            start_time=time.time(),
        )

        assert any("<system_note>Interrupted</system_note>" in m.get("content", "") for m in agent.history)


# ============================================================================
# 2. History Compaction and Interruption Sanitization
# ============================================================================


class TestCompactionAndSanitization:
    """Tests for LLM history sanitization and compaction when interruptions occur."""

    def test_is_system_note_detection(self):
        assert is_system_note({"role": "user", "content": "<system_note>Interrupted</system_note>"}) is True
        assert is_system_note({"role": "user", "content": "<system_note>Custom message</system_note>"}) is True
        assert is_system_note({"role": "user", "content": "Just a normal user message"}) is False
        assert is_system_note({"role": "assistant", "content": "Sure, here is the answer"}) is False
        assert is_system_note("Not a dict") is False
        assert is_system_note(None) is False

    def test_sanitize_history_injects_synthetic_results_for_interrupted_tool_calls(self):
        # Scenario: Assistant issued 2 tool calls, execution was interrupted before any tool returned
        agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
        history = [
            {"role": "user", "content": "Run tools"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "shell", "arguments": '{"cmd":"ls"}'}},
                    {"id": "call_2", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'}},
                ],
            },
            {"role": "user", "content": "<system_note>Interrupted</system_note>"},
        ]

        sanitized = agent.sanitize_history_for_model(history)

        # There should now be synthetic tool response messages injected for call_1 and call_2
        assert len(sanitized) == 5
        tool_res_1 = sanitized[2]
        tool_res_2 = sanitized[3]

        assert tool_res_1["role"] == "tool"
        assert tool_res_1["tool_call_id"] == "call_1"
        assert "interrupted or cancelled" in tool_res_1["content"]

        assert tool_res_2["role"] == "tool"
        assert tool_res_2["tool_call_id"] == "call_2"
        assert "interrupted or cancelled" in tool_res_2["content"]

        assert sanitized[4]["content"] == "<system_note>Interrupted</system_note>"

    def test_sanitize_history_partial_tool_completion_then_interrupted(self):
        # Scenario: call_1 completed, but call_2 was interrupted
        agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
        history = [
            {"role": "user", "content": "Run tools"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "shell", "arguments": '{"cmd":"ls"}'}},
                    {"id": "call_2", "type": "function", "function": {"name": "shell", "arguments": '{"cmd":"top"}'}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "shell", "content": "file1.txt\nfile2.txt"},
            {"role": "user", "content": "<system_note>Interrupted</system_note>"},
        ]

        sanitized = agent.sanitize_history_for_model(history)
        assert len(sanitized) == 5
        assert sanitized[2]["tool_call_id"] == "call_1"
        assert sanitized[2]["content"] == "file1.txt\nfile2.txt"

        # call_2 got synthetic cancellation
        assert sanitized[3]["tool_call_id"] == "call_2"
        assert "interrupted or cancelled" in sanitized[3]["content"]

    def test_collect_user_messages_skips_interruption_notes(self):
        history = [
            {"role": "user", "content": "Turn 1"},
            {"role": "assistant", "content": "Reply 1"},
            {"role": "user", "content": "<system_note>Interrupted</system_note>"},
            {"role": "user", "content": "Turn 2"},
        ]
        collected = collect_user_messages(history)
        contents = [m["content"] for m in collected]
        assert contents == ["Turn 1", "Turn 2"]

    def test_truncate_history_skips_interruption_system_notes(self):
        agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
        agent.history = [
            {"role": "user", "content": "Turn 0"},
            {"role": "assistant", "content": "Resp 0"},
            {"role": "user", "content": "<system_note>Interrupted</system_note>"},
            {"role": "user", "content": "Turn 1"},
            {"role": "assistant", "content": "Resp 1"},
        ]

        # Truncate to index 1 (second real user turn -> keeps Turn 0)
        agent.truncate_history_to_user_message(1)
        contents = [m["content"] for m in agent.history]
        assert contents == ["Turn 0", "Resp 0"]


# ============================================================================
# 3. UI Key Routing in ChatInput (Escape handling)
# ============================================================================


class DummyChatApp(App[None]):
    def __init__(self, chat_input):
        super().__init__()
        self.chat_input = chat_input
        self.exited = False

    def compose(self) -> ComposeResult:
        yield self.chat_input

    def exit(self, *args, **kwargs):
        self.exited = True


class TestChatInputEscapeRouting:
    """Tests for Escape key routing in ChatInput widget."""

    @pytest.mark.asyncio
    async def test_escape_closes_suggestions_popup_without_cancelling_workers(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            mock_worker = MagicMock()
            mock_worker.is_running = True
            with patch.object(App, "workers", new_callable=PropertyMock, return_value=[mock_worker]):
                mock_suggestions = MagicMock()
                mock_suggestions.display = True

                with patch.object(app, "query_one", return_value=mock_suggestions):
                    event = Key("escape", "escape")
                    event.prevent_default = MagicMock()
                    event.stop = MagicMock()

                    await ci._on_key(event)

                    assert mock_suggestions.display is False
                    mock_worker.cancel.assert_not_called()
                    event.prevent_default.assert_called_once()
                    event.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_escape_cancels_active_workers_when_no_suggestions_popup(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            worker1 = MagicMock(is_running=True)
            worker2 = MagicMock(is_running=False)
            worker3 = MagicMock(is_running=True)
            with patch.object(App, "workers", new_callable=PropertyMock, return_value=[worker1, worker2, worker3]):
                event = Key("escape", "escape")
                event.prevent_default = MagicMock()
                event.stop = MagicMock()

                await ci._on_key(event)

                worker1.cancel.assert_called_once()
                worker2.cancel.assert_not_called()
                worker3.cancel.assert_called_once()
                event.prevent_default.assert_called_once()
                event.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_ctrl_c_and_ctrl_q_quit_app(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            for quit_key in KEY_QUIT:
                app.exited = False
                event = Key(quit_key, quit_key)
                event.prevent_default = MagicMock()
                event.stop = MagicMock()

                await ci._on_key(event)

                assert app.exited is True
                event.prevent_default.assert_called_once()
                event.stop.assert_called_once()


# ============================================================================
# 4. ToolCallWidget Cancellation State
# ============================================================================


class TestChatToolCallCancellation:
    """Tests for ToolCallWidget mark_cancelled behavior."""

    def test_mark_cancelled_updates_status_and_result(self):
        widget = ToolCallWidget(tool_type="shell", target="long_task.sh", args={"cmd": "long_task.sh"})
        assert widget.status == "running"

        widget.mark_cancelled()

        assert widget.status == "cancelled"
        assert "interrupted or cancelled" in widget.result_text
        assert widget.is_expandable() is True

    def test_mark_cancelled_is_noop_if_not_running(self):
        widget = ToolCallWidget(tool_type="shell", target="done_task.sh", result_text="All done", status="done")
        assert widget.status == "done"

        widget.mark_cancelled()
        assert widget.status == "done"
        assert widget.result_text == "All done"


# ============================================================================
# 5. Session Filtering and Interruption State
# ============================================================================


class TestSessionInterruptionFiltering:
    """Tests for session message filtering and rewind logic with interruption notes."""

    def test_is_ui_visible_user_message_filters_interruption_note(self):
        normal_msg = {"type": "user", "text": "Can you check this?"}
        interruption_note = {"type": "user", "text": "[System Note: Response interrupted by user]"}
        short_interruption_note = {"type": "user", "text": "[System Note: Response interrupted]"}

        assert is_ui_visible_user_message(normal_msg) is True
        assert is_ui_visible_user_message(interruption_note) is False
        assert is_ui_visible_user_message(short_interruption_note) is False

    def test_session_records_event_divider_properly(self):
        sess = AgentSession(session_id="test_sess", role="assistant")
        sess.add_event({"type": "event_divider", "text": "Response Interrupted"})

        assert len(sess.messages) == 1
        assert sess.messages[0]["type"] == "event_divider"
        assert sess.messages[0]["text"] == "Response Interrupted"


# ============================================================================
# 6. Generator Stream Interruption Integration Flow
# ============================================================================


class TestGeneratorStreamInterruptionFlow:
    """Integration-style tests for generate_ai_response interrupted mid-stream."""

    @pytest.mark.asyncio
    async def test_cancellation_during_thinking_stream(self):
        async def mock_stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            yield ("thinking_delta", "step 1", "")
            raise asyncio.CancelledError()

        agent = MagicMock()
        agent.stream_steps = mock_stream
        agent.history = [{"role": "user", "content": "Do work"}]
        agent._last_sys_tokens = 0

        session = AgentSession(session_id="s_test", role="assistant")

        mock_thinking = MagicMock()
        mock_thinking.is_thinking = True

        def finish_t(duration):
            mock_thinking.is_thinking = False

        mock_thinking.finish_thinking = MagicMock(side_effect=finish_t)

        canvas = _make_canvas(
            add_thinking_widget=AsyncMock(return_value=mock_thinking),
        )

        with pytest.raises(asyncio.CancelledError):
            await generate_ai_response(
                agent=agent,
                session=session,
                canvas=canvas,
                session_id="s_test",
                user_text="Do work",
            )

        # Thinking finished
        mock_thinking.finish_thinking.assert_called_once()
        # Divider added
        canvas.add_event_divider.assert_awaited_once_with("Response Interrupted")
        # System note in history
        assert any("<system_note>Interrupted</system_note>" in m["content"] for m in agent.history)

    @pytest.mark.asyncio
    async def test_cancellation_during_bot_delta_stream(self):
        async def mock_stream(prompt, attachments=None):
            yield ("bot_delta", "Chunk 1 ", "")
            yield ("bot_delta", "Chunk 2", "")
            raise asyncio.CancelledError()

        agent = MagicMock()
        agent.stream_steps = mock_stream
        agent.history = [{"role": "user", "content": "Generate story"}]
        agent._last_sys_tokens = 0

        session = AgentSession(session_id="s_test", role="assistant")

        mock_bot = MagicMock()
        mock_bot.content = ""

        def append_content(c):
            mock_bot.content += c

        mock_bot.append_stream_content = MagicMock(side_effect=append_content)
        mock_bot.finalize_stream = AsyncMock()

        canvas = _make_canvas(
            add_bot_message=AsyncMock(return_value=mock_bot),
        )

        with pytest.raises(asyncio.CancelledError):
            await generate_ai_response(
                agent=agent,
                session=session,
                canvas=canvas,
                session_id="s_test",
                user_text="Generate story",
            )

        # Partial bot finalized
        mock_bot.finalize_stream.assert_awaited_once()
        # History has partial response and system note
        assert len(agent.history) == 3
        assert agent.history[1] == {"role": "assistant", "content": "Chunk 1 Chunk 2"}
        assert agent.history[2] == {
            "role": "user",
            "content": "<system_note>Interrupted</system_note>",
        }

    @pytest.mark.asyncio
    async def test_cancellation_during_tool_execution_stream(self):
        mock_tool_widget = MagicMock()

        async def mock_stream(prompt, attachments=None):
            yield ("tool", "shell", "run", {"cmd": "sleep 10"})
            raise asyncio.CancelledError()

        agent = MagicMock()
        agent.stream_steps = mock_stream
        agent.history = [{"role": "user", "content": "Run tool"}]
        agent._last_sys_tokens = 0

        session = AgentSession(session_id="s_test", role="assistant")

        canvas = _make_canvas(
            add_tool_call=AsyncMock(return_value=mock_tool_widget),
        )

        with pytest.raises(asyncio.CancelledError):
            await generate_ai_response(
                agent=agent,
                session=session,
                canvas=canvas,
                session_id="s_test",
                user_text="Run tool",
            )

        # Tool widget marked cancelled
        mock_tool_widget.mark_cancelled.assert_called_once()
        canvas.add_event_divider.assert_awaited_once_with("Response Interrupted")

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_during_tool_execution_stream(self):
        mock_tool_widget = MagicMock()

        async def mock_stream(prompt, attachments=None):
            yield ("tool", "ask_user", "What next?", {"questions": []})
            raise KeyboardInterrupt()

        agent = MagicMock()
        agent.stream_steps = mock_stream
        agent.history = [{"role": "user", "content": "Ask"}]
        agent._last_sys_tokens = 0

        session = AgentSession(session_id="s_test", role="assistant")

        canvas = _make_canvas(
            add_tool_call=AsyncMock(return_value=mock_tool_widget),
        )

        with pytest.raises(KeyboardInterrupt):
            await generate_ai_response(
                agent=agent,
                session=session,
                canvas=canvas,
                session_id="s_test",
                user_text="Ask",
            )

        # Tool widget marked cancelled even on raw KeyboardInterrupt
        mock_tool_widget.mark_cancelled.assert_called_once()
        canvas.add_event_divider.assert_awaited_once_with("Response Interrupted")
        assert any("<system_note>Interrupted</system_note>" in m["content"] for m in agent.history)

    def test_ask_user_wizard_screen_has_quit_bindings(self):
        from widgets.presentation.screens.ask_user import AskUserWizardScreen

        keys = [b[0] for b in AskUserWizardScreen.BINDINGS]
        assert "ctrl+c" in keys
        assert "ctrl+q" in keys

    def test_mark_cancelled_preserves_accumulated_shell_output(self):
        from widgets.chat_toolcall import ToolCallWidget

        w = ToolCallWidget("shell", "pytest")
        w.status = "running"
        w.result_text = "PASSED test_1.py\nFAILED test_2.py"
        w.mark_cancelled()
        assert w.status == "cancelled"
        assert "PASSED test_1.py" in w.result_text
        assert "FAILED test_2.py" in w.result_text
        assert "[Command interrupted by user]" in w.result_text
        # Clickable / expandable if output is present
        assert w.is_clickable_header() is True

    def test_mark_cancelled_without_prior_output_sets_default_message(self):
        from widgets.chat_toolcall import ToolCallWidget

        w = ToolCallWidget("shell", "pytest")
        w.status = "running"
        w.result_text = ""
        w.mark_cancelled()
        assert w.status == "cancelled"
        assert w.result_text == "[Tool call interrupted or cancelled]"

    def test_shell_expand_loads_background_log_file(self, tmp_path):
        from widgets.chat_toolcall import ToolCallWidget

        log_f = tmp_path / "test.log"
        log_f.write_text("collected 50 items\n50 passed in 2.0s\n")

        w = ToolCallWidget(
            "shell",
            "pytest -m slow",
            result_text=f"[Background Task ID: 123] moved to background.\nFull Log: {log_f} (live)",
            status="done",
        )
        kind, content = w._compute_content()
        assert kind == "markup"
        assert "50 passed in 2.0s" in content

    @pytest.mark.asyncio
    async def test_cancellation_after_completed_tool_does_not_create_orphan_cancelled_tool(self):
        mock_tool_widget = MagicMock()
        mock_tool_widget.result_text = "file1\nfile2"
        mock_tool_widget.status = "done"

        async def mock_stream(prompt, attachments=None):
            yield ("tool", "shell", "run", {"cmd": "ls"})
            yield ("tool_result", "file1\nfile2", "")
            yield ("bot_delta", "Here are the files: ", "")
            raise asyncio.CancelledError()

        agent = MagicMock()
        agent.stream_steps = mock_stream
        agent.history = [{"role": "user", "content": "List files"}]
        agent._last_sys_tokens = 0

        session = AgentSession(session_id="s_test", role="assistant")

        canvas = _make_canvas(
            add_tool_call=AsyncMock(return_value=mock_tool_widget),
        )

        with pytest.raises(asyncio.CancelledError):
            await generate_ai_response(
                agent=agent,
                session=session,
                canvas=canvas,
                session_id="s_test",
                user_text="List files",
            )

        # Completed tool widget was NOT cancelled
        mock_tool_widget.mark_cancelled.assert_not_called()
        mock_tool_widget.set_result.assert_called_once()

        # Session should have exactly 1 tool event with tool_type, NOT an extra empty cancelled tool event
        tool_events = [m for m in session.messages if m.get("type") == "tool"]
        assert len(tool_events) == 1
        assert tool_events[0].get("tool_type") == "shell"
        assert tool_events[0].get("status") != "cancelled"
        assert any(m.get("type") == "event_divider" for m in session.messages)
