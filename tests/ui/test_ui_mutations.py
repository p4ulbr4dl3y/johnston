from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from johnston.core.application.generation.engine import ProviderReadyState
from johnston.tui.mixins.message_flow import MessageFlowMixin
from johnston.tui.presentation.commands.session_commands import CompactCommand
from johnston.tui.presentation.widgets.chat_messages import ThinkingWidget
from johnston.tui.presentation.widgets.chat_toolcall import ToolCallWidget
from johnston.tui.presentation.widgets.chat_view_restore import restore_message_item

# ==============================================================================
# 1. ToolCallActionsMixin / has_subagent_session pure predicate & explicit binding
# ==============================================================================

def test_has_subagent_session_is_pure_predicate_no_mutation():
    widget = ToolCallWidget(
        tool_type="invoke_subagent",
        target="research",
        result_text="Task started session_id: sess_xyz_123",
        args={},
    )
    # Manually clear subagent_session_id to verify getter does not re-mutate
    widget.subagent_session_id = None

    # Call getter
    result = widget.has_subagent_session()
    assert result is True
    # Crucial check: getter must NOT have mutated subagent_session_id
    assert widget.subagent_session_id is None

    # Explicit bind call DOES set it
    bound = widget.bind_subagent_session()
    assert bound == "sess_xyz_123"
    assert widget.subagent_session_id == "sess_xyz_123"


def test_has_subagent_session_store_lookup_no_mutation():
    widget = ToolCallWidget(
        tool_type="invoke_subagent",
        target="worker",
        result_text="",
        args={"title": "subagent-task"},
    )
    widget.subagent_session_id = None

    mock_session = MagicMock(id="store_sess_999")
    mock_store = MagicMock()
    mock_store.find_session_by_title_or_id.return_value = mock_session

    mock_app = MagicMock()
    mock_app.sm = mock_store
    mock_app.current_session_id = "parent-1"
    with patch.object(ToolCallWidget, "app", new_callable=lambda: mock_app):
        assert widget.has_subagent_session() is True
        # Must NOT mutate
        assert widget.subagent_session_id is None

        # Explicit binding
        bound = widget.bind_subagent_session()
        assert bound == "store_sess_999"
        assert widget.subagent_session_id == "store_sess_999"


# ==============================================================================
# 2. chat_view_restore: no in-place mutation of input history dictionary
# ==============================================================================

@pytest.mark.asyncio
async def test_restore_message_item_does_not_mutate_msg_dict():
    mock_chat_view = MagicMock()
    mock_chat_view.add_tool_call = AsyncMock(return_value=MagicMock())

    mock_session = MagicMock(id="found_sess_456")
    mock_store = MagicMock()
    mock_store.find_session_by_title_or_id.return_value = mock_session

    mock_app = MagicMock()
    mock_app.sm = mock_store
    mock_app.current_session_id = "main"
    mock_chat_view.app = mock_app

    input_msg = {
        "type": "tool",
        "tool_type": "invoke_subagent",
        "target": "worker",
        "args": {"title": "Find Subagent"},
        "result_text": "working",
        "status": "done",
    }

    # Shallow copy keys snapshot
    keys_before = set(input_msg.keys())
    assert "subagent_session_id" not in input_msg

    await restore_message_item(mock_chat_view, input_msg)

    # Input dictionary must remain unmodified!
    assert "subagent_session_id" not in input_msg
    assert set(input_msg.keys()) == keys_before

    # But subagent_session_id was passed directly as keyword arg
    mock_chat_view.add_tool_call.assert_awaited_once()
    _, kwargs = mock_chat_view.add_tool_call.call_args
    assert kwargs.get("subagent_session_id") == "found_sess_456"


# ==============================================================================
# 3. message_flow: timing of is_generating flag and ensure_provider_ready
# ==============================================================================

class DummyFlowApp(MessageFlowMixin):
    def __init__(self):
        self.is_generating = False
        self._is_compacting = False
        self.message_queue = []
        self.pm = MagicMock()
        self.agent = MagicMock()
        self.current_session_id = "sess-flow"
        self.sm = MagicMock()
        self.query_one = MagicMock()
        self.refresh_status_footer = MagicMock()
        self.notify = MagicMock()
        self.save_current_session_async = AsyncMock()


def test_trigger_ai_response_does_not_set_is_generating_immediately():
    app = DummyFlowApp()
    app.generate_ai_response = MagicMock()

    assert app.is_generating is False
    app.trigger_ai_response("hello")

    # trigger_ai_response should not mutate is_generating before generator runs
    assert app.is_generating is False
    app.generate_ai_response.assert_called_once_with("hello", show_in_ui=False)


@pytest.mark.asyncio
async def test_generate_ai_response_leaves_is_generating_false_when_provider_not_ready():
    app = DummyFlowApp()

    with patch(
        "johnston.core.application.generation.engine.ensure_provider_ready",
        return_value=ProviderReadyState.NEEDS_PROVIDER,
    ), patch(
        "johnston.tui.presentation.commands.ProvidersCommand.execute",
        new_callable=AsyncMock,
    ) as mock_prov_cmd:
        # Call the underlying coroutine of the worker method directly
        target_fn = getattr(MessageFlowMixin.generate_ai_response, "__wrapped__", MessageFlowMixin.generate_ai_response)
        await target_fn(app, "hello")

        mock_prov_cmd.assert_awaited_once_with(app)
        # is_generating must remain False during and after modal execution
        assert app.is_generating is False


# ==============================================================================
# 4. CompactCommand: state decoupling (_is_compacting instead of is_generating)
# ==============================================================================

@pytest.mark.asyncio
async def test_compact_command_uses_is_compacting_flag_not_is_generating():
    class MockApp:
        def __init__(self):
            self.is_generating = False
            self.is_compacting = False
            self._is_compacting = False
            self.agent = MagicMock()
            self.refresh_status_footer = MagicMock()
            self.notified = []

        def notify(self, msg, severity="info"):
            self.notified.append((msg, severity))

    app = MockApp()
    command = CompactCommand()

    seen_during_compact = {}

    async def fake_compact(agent, **kwargs):
        seen_during_compact["is_generating"] = app.is_generating
        seen_during_compact["is_compacting"] = app.is_compacting
        seen_during_compact["_is_compacting"] = app._is_compacting
        kwargs["on_begin"]()
        seen_during_compact["on_begin_is_generating"] = app.is_generating
        seen_during_compact["on_begin_is_compacting"] = app.is_compacting
        from types import SimpleNamespace
        return SimpleNamespace(success=True, message="ok")

    with patch("johnston.tui.presentation.commands.session_commands.compact_session", new=fake_compact):
        await command.execute(app)

    # During compaction:
    assert seen_during_compact["is_generating"] is False
    assert seen_during_compact["is_compacting"] is True
    assert seen_during_compact["_is_compacting"] is True
    assert seen_during_compact["on_begin_is_generating"] is False
    assert seen_during_compact["on_begin_is_compacting"] is True

    # After compaction:
    assert app.is_generating is False
    assert app.is_compacting is False
    assert app._is_compacting is False


@pytest.mark.asyncio
async def test_compact_command_defers_when_already_compacting():
    app = MagicMock()
    app.is_generating = False
    app.is_compacting = True
    app._queue_message_ui = MagicMock()

    command = CompactCommand()
    await command.execute(app)

    app._queue_message_ui.assert_called_once_with(command.name, show_in_ui=True)


# ==============================================================================
# 5. ThinkingWidget: is_active=False avoids scheduling hint timer
# ==============================================================================

@pytest.mark.asyncio
async def test_thinking_widget_is_active_false_does_not_schedule_timer():
    # Active thinking widget (default)
    tw_active = ThinkingWidget("Processing...", is_active=True)
    assert tw_active.is_thinking is True
    assert tw_active._hint_handle is not None
    tw_active._cancel_hint_timer()

    # Archived / restored thinking widget
    tw_archive = ThinkingWidget("Old thoughts", is_active=False)
    assert tw_archive.is_thinking is False
    assert tw_archive._hint_handle is None
    assert "thinking-active" not in tw_archive.classes


@pytest.mark.asyncio
async def test_restore_message_item_passes_is_active_false_to_thinking():
    mock_chat_view = MagicMock()
    mock_thinking_widget = MagicMock(spec=ThinkingWidget)
    mock_chat_view.add_thinking_widget = AsyncMock(return_value=mock_thinking_widget)

    msg = {
        "type": "thinking",
        "text": "Deep thinking completed in history",
        "duration": 4.5,
    }

    tw = await restore_message_item(mock_chat_view, msg)
    assert tw is mock_thinking_widget

    mock_chat_view.add_thinking_widget.assert_awaited_once_with(
        animate=False,
        is_active=False,
    )
    mock_thinking_widget.finish_thinking.assert_called_once_with(4.5, "Deep thinking completed in history")
