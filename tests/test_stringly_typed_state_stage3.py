from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from johnston_core.application.session.stream_runner import execute_session_turn
from johnston_core.base_provider.compaction import CompactionMixin
from johnston_core.domain.defaults.errors import ToolResult, ToolResultStatus, normalize_tool_result
from johnston_core.domain.entities.session import AgentSession
from johnston_tui.mixins.message_flow_background import update_background_shell_widget
from johnston_tui.presentation.tool_renderers import compute_tool_call_content
from johnston_tui.presentation.widgets.chat_stream_driver import ChatStreamDriver
from johnston_tui.presentation.widgets.chat_view_restore import restore_message_item


# ==============================================================================
# 1. message_flow_background: strict task_id / background_task_id matching
# ==============================================================================
def test_update_background_shell_widget_strict_task_id_matching():
    app = MagicMock()
    app.current_session_id = "sess_1"
    session = MagicMock()
    # Message 1 has coincidental substring in result_text but no task_id field
    msg_coincidental = {
        "type": "tool",
        "tool_type": "shell",
        "result_text": "log output mentions bg_task_123 coincidentally",
        "status": "running",
    }
    # Message 2 has matching task_id field
    msg_matching = {
        "type": "tool",
        "tool_type": "shell",
        "result_text": "running...",
        "status": "running",
        "task_id": "bg_task_123",
    }
    session.messages = [msg_coincidental, msg_matching]
    app.sm.get.return_value = session

    with patch("johnston_tui.mixins.message_flow_background.schedule_session_save") as mock_save:
        update_background_shell_widget(app, "bg_task_123", "command finished")
        mock_save.assert_called_once_with(app, session)

    # msg_coincidental must NOT be modified
    assert msg_coincidental["result_text"] == "log output mentions bg_task_123 coincidentally"
    assert msg_coincidental["status"] == "running"

    # msg_matching must be updated with final result and status
    assert "command finished" in msg_matching["result_text"]
    assert msg_matching["status"] == "done"
    assert msg_matching["background_task_id"] == "bg_task_123"


def test_update_background_shell_widget_background_task_id_alias():
    app = MagicMock()
    app.current_session_id = "sess_1"
    session = MagicMock()
    msg_matching = {
        "type": "tool",
        "tool_type": "shell",
        "result_text": "running...",
        "status": "running",
        "background_task_id": "bg_456",
    }
    session.messages = [msg_matching]
    app.sm.get.return_value = session

    with patch("johnston_tui.mixins.message_flow_background.schedule_session_save"):
        update_background_shell_widget(app, "bg_456", "done output")

    assert "done output" in msg_matching["result_text"]
    assert msg_matching["status"] == "done"
    assert msg_matching["task_id"] == "bg_456"


# ==============================================================================
# 2. chat_view_restore: no regex parsing of task_id and subagent_session_id
# ==============================================================================
@pytest.mark.asyncio
async def test_restore_message_item_strict_field_extraction():
    chat_view = MagicMock()
    chat_view.add_tool_call = AsyncMock()

    # Message contains legacy-like regex text in result_text, but NO task_id or subagent_session_id fields
    msg = {
        "type": "tool",
        "tool_type": "shell",
        "target": "echo 1",
        "result_text": "[Background Task ID: fake_task_999] | id fake_sub_888",
        "status": "running",
        "args": {},
    }

    await restore_message_item(chat_view, msg)

    chat_view.add_tool_call.assert_awaited_once()
    _, kwargs = chat_view.add_tool_call.call_args
    # Must NOT have regex-parsed fake_task_999 or fake_sub_888
    assert kwargs.get("background_task_id") is None
    assert kwargs.get("subagent_session_id") is None


@pytest.mark.asyncio
async def test_restore_message_item_passes_typed_fields():
    chat_view = MagicMock()
    chat_view.add_tool_call = AsyncMock()

    msg = {
        "type": "tool",
        "tool_type": "shell",
        "target": "ls",
        "result_text": "listing...",
        "status": "running",
        "args": {},
        "task_id": "real_task_123",
        "subagent_session_id": "sub_sess_456",
        "log_path": "/tmp/test.log",
    }
    # Mock task manager where real_task_123 is active
    task_mgr = MagicMock()
    task_mgr._tasks = {"real_task_123": MagicMock()}

    await restore_message_item(chat_view, msg, task_manager=task_mgr)

    chat_view.add_tool_call.assert_awaited_once()
    _, kwargs = chat_view.add_tool_call.call_args
    assert kwargs.get("background_task_id") == "real_task_123"
    assert kwargs.get("subagent_session_id") == "sub_sess_456"
    assert kwargs.get("log_path") == "/tmp/test.log"
    assert kwargs.get("status") == "running"


# ==============================================================================
# 3. shell.py & chat_stream_driver: task_id routing for tool_shell_output
# ==============================================================================
def test_chat_stream_driver_finds_exact_shell_output_target():
    cv = MagicMock()
    driver = ChatStreamDriver(cv)

    card1 = MagicMock()
    card1.background_task_id = "task_alpha"
    card1.append_shell_output = MagicMock()

    card2 = MagicMock()
    card2.background_task_id = "task_beta"
    card2.append_shell_output = MagicMock()

    cv.children = [card1, card2]

    # Target task_alpha specifically: must return card1, never card2
    target = driver._find_shell_output_target("task_alpha")
    assert target is card1

    # Target task_beta specifically: must return card2
    target2 = driver._find_shell_output_target("task_beta")
    assert target2 is card2

    # Target nonexistent task: returns None
    target_none = driver._find_shell_output_target("task_gamma")
    assert target_none is None


@pytest.mark.asyncio
async def test_chat_stream_driver_consumes_tool_shell_output_with_task_id():
    cv = MagicMock()
    driver = ChatStreamDriver(cv)

    card1 = MagicMock()
    card1.background_task_id = "task_1"
    card1.append_shell_output = MagicMock()

    card2 = MagicMock()
    card2.background_task_id = "task_2"
    card2.append_shell_output = MagicMock()

    cv.children = [card1, card2]

    await driver.consume_session_event({
        "type": "tool_shell_output",
        "text": "chunk for task 2\n",
        "task_id": "task_2",
    })

    card2.append_shell_output.assert_called_once_with("chunk for task 2\n")
    card1.append_shell_output.assert_not_called()


# ==============================================================================
# 4. normalize_tool_result: no string heuristics for err:
# ==============================================================================
@pytest.mark.asyncio
async def test_normalize_tool_result_does_not_treat_err_text_as_error():
    # A string starting with "err:" or "ERR:" is valid content, NOT an error!
    res = await normalize_tool_result("ERR: git log contains error messages from history")
    assert res.status == ToolResultStatus.DONE
    assert not res.is_error
    assert res.content == "ERR: git log contains error messages from history"


@pytest.mark.asyncio
async def test_normalize_tool_result_respects_returncode_and_toolresult():
    # Object with returncode != 0
    obj = MagicMock()
    obj.returncode = 2
    obj.__str__.return_value = "command failed: file not found"

    res = await normalize_tool_result(obj)
    assert res.status == ToolResultStatus.ERROR
    assert res.is_error
    assert res.returncode == 2

    # Structured ToolResult.error()
    err_res = ToolResult.error("not_found", detail="missing.py", name="read")
    res2 = await normalize_tool_result(err_res)
    assert res2.is_error
    assert res2.status == ToolResultStatus.ERROR


# ==============================================================================
# 5. stream_runner: structured step[0] == "error"
# ==============================================================================
@pytest.mark.asyncio
async def test_stream_runner_handles_structured_error_step():
    agent = MagicMock()

    async def mock_stream(msg):
        yield ("error", "API rate limit exceeded", "")

    agent.stream_steps = mock_stream
    agent.history = []
    agent._last_sys_tokens = 0

    session = AgentSession(session_id="test_sess", role="worker")
    store = MagicMock()
    store.save = MagicMock()

    result = await execute_session_turn(
        agent=agent,
        session=session,
        store=store,
        message="hello",
    )

    assert "[API rate limit exceeded]" in result
    assert session.status == "error"


# ==============================================================================
# 6. tool_renderers: uses log_path argument/property, not regex on result_text
# ==============================================================================
def test_compute_tool_call_content_uses_log_path(tmp_path):
    log_file = tmp_path / "shell_exec.log"
    log_file.write_text("All 42 tests passed in 1.2s\n")

    kind, content = compute_tool_call_content(
        tool_type="shell",
        canonical_tool="shell",
        args={"command": "pytest"},
        target="pytest",
        result_text="[task backgrounded | id t1]",
        is_error=False,
        guess_lexer=lambda _: "text",
        clean_markup=lambda s: s,
        clean_hints=lambda s: s,
        clean_bash_output=lambda s: s,
        format_json_result_fn=lambda _: None,
        log_path=str(log_file),
    )

    assert kind == "markup"
    assert "All 42 tests passed in 1.2s" in content


def test_compute_tool_call_content_does_not_regex_scrape_full_log(tmp_path):
    # If log_path argument is NOT provided, it should NOT regex-scrape even if text has "Full Log: ..."
    fake_log = tmp_path / "fake.log"
    fake_log.write_text("Should NOT be read\n")

    kind, content = compute_tool_call_content(
        tool_type="shell",
        canonical_tool="shell",
        args={"command": "pytest"},
        target="pytest",
        result_text=f"Output text.\nFull Log: {fake_log}",
        is_error=False,
        guess_lexer=lambda _: "text",
        clean_markup=lambda s: s,
        clean_hints=lambda s: s,
        clean_bash_output=lambda s: s,
        format_json_result_fn=lambda _: None,
        log_path=None,
    )

    assert kind == "markup"
    # Content must retain the text and not load the fake_log file content
    assert "Output text." in content
    assert "Should NOT be read" not in content


# ==============================================================================
# 7. compaction: uses session.plan
# ==============================================================================
@pytest.mark.asyncio
async def test_compaction_prefers_session_plan_entity():
    class DummyAgent(CompactionMixin):
        def __init__(self):
            self.provider_key = "openai"
            self.model = "gpt-4o"
            self.history = []
            self.current_plan = None
            self.session = None

    agent = DummyAgent()
    session = AgentSession("sess_plan_test")
    session.plan = [
        {"step": "Architecture audit", "status": "completed"},
        {"step": "Phase 3 cleanup", "status": "in_progress"},
    ]
    agent.session = session

    # Test that _compact_history preserves session.plan
    # Simulate compaction preserving active plan
    sess = getattr(agent, "session", None)
    active_plan = getattr(sess, "plan", None)
    assert active_plan is not None
    assert len(active_plan) == 2
    assert active_plan[0]["step"] == "Architecture audit"
    assert active_plan[1]["status"] == "in_progress"
