from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from johnston.core.dto import (
    CommandResultDTO,
    CompactionEventDTO,
    CompactionResultDTO,
    ContentDeltaDTO,
    ErrorEventDTO,
    GitStateDTO,
    MessageDTO,
    ModelInfoDTO,
    PermissionRequestDTO,
    ProviderDTO,
    RewindPointDTO,
    RuleDTO,
    SessionDTO,
    SessionSummaryDTO,
    SkillDTO,
    StreamEventDTO,
    TaskDTO,
    ThinkingDeltaDTO,
    ToolCallDTO,
    ToolResultDTO,
    TurnCompletedDTO,
    parse_event_dto,
)


def test_frozen_behavior():
    event = ContentDeltaDTO(text="hello")
    with pytest.raises(FrozenInstanceError):
        event.text = "world"  # type: ignore[misc]

    session = SessionDTO(id="123", title="test", created_at=1.0, updated_at=2.0)
    with pytest.raises(FrozenInstanceError):
        session.title = "changed"  # type: ignore[misc]


def test_slots_defined():
    event = ContentDeltaDTO(text="test")
    assert hasattr(event, "__slots__")
    assert not hasattr(event, "__dict__")

    rewind = RewindPointDTO(index=1, text="turn 1")
    assert hasattr(rewind, "__slots__")
    assert not hasattr(rewind, "__dict__")


def test_events_creation():
    content = ContentDeltaDTO(text="chunk")
    assert content.text == "chunk"
    assert isinstance(content, StreamEventDTO)

    thinking = ThinkingDeltaDTO(thought="thinking...")
    assert thinking.thought == "thinking..."

    tool_call = ToolCallDTO(tool_name="bash", args={"cmd": "ls"}, call_id="call_1")
    assert tool_call.tool_name == "bash"
    assert tool_call.args == {"cmd": "ls"}
    assert tool_call.call_id == "call_1"

    tool_res = ToolResultDTO(
        tool_name="bash",
        content="file.txt",
        is_error=False,
        status="done",
        returncode=0,
    )
    assert tool_res.tool_name == "bash"
    assert tool_res.content == "file.txt"
    assert not tool_res.is_error
    assert tool_res.status == "done"
    assert tool_res.returncode == 0

    compaction = CompactionEventDTO(summary="compacted")
    assert compaction.summary == "compacted"

    turn_comp = TurnCompletedDTO(duration_s=1.5, usage={"tokens": 100})
    assert turn_comp.duration_s == 1.5
    assert turn_comp.usage == {"tokens": 100}

    err = ErrorEventDTO(message="Failed", fatal=True)
    assert err.message == "Failed"
    assert err.fatal is True


def test_parse_event_dto_content():
    evt = parse_event_dto(("content", "hello world"))
    assert isinstance(evt, ContentDeltaDTO)
    assert evt.text == "hello world"

    evt2 = parse_event_dto(("bot_delta", "partial", ""))
    assert isinstance(evt2, ContentDeltaDTO)
    assert evt2.text == "partial"

    evt3 = parse_event_dto(("bot_text", "full text"))
    assert isinstance(evt3, ContentDeltaDTO)
    assert evt3.text == "full text"

    evt4 = parse_event_dto(("outro", "farewell"))
    assert isinstance(evt4, ContentDeltaDTO)
    assert evt4.text == "farewell"


def test_parse_event_dto_thinking():
    evt = parse_event_dto(("thinking_delta", "step 1", ""))
    assert isinstance(evt, ThinkingDeltaDTO)
    assert evt.thought == "step 1"

    evt2 = parse_event_dto(("thinking_start", "Thinking...", ""))
    assert isinstance(evt2, ThinkingDeltaDTO)
    assert evt2.thought == "Thinking..."

    evt3 = parse_event_dto(("thinking", "auto-compacting", ""))
    assert isinstance(evt3, ThinkingDeltaDTO)
    assert evt3.thought == "auto-compacting"


def test_parse_event_dto_tool_call():
    # standard 5-tuple: ("tool", name, target, args, id)
    evt = parse_event_dto(("tool", "view_file", "path/to/f", {"path": "path/to/f"}, "call_99"))
    assert isinstance(evt, ToolCallDTO)
    assert evt.tool_name == "view_file"
    assert evt.args == {"path": "path/to/f"}
    assert evt.call_id == "call_99"

    # tool_call with json string args
    evt2 = parse_event_dto(("tool_call", "run_cmd", '{"cmd": "pwd"}', "call_100"))
    assert isinstance(evt2, ToolCallDTO)
    assert evt2.tool_name == "run_cmd"
    assert evt2.args == {"cmd": "pwd"}
    assert evt2.call_id == "call_100"

    # dict payload tool_name
    evt3 = parse_event_dto(("tool_call", {"name": "grep", "args": {"q": "foo"}, "id": "call_101"}))
    assert isinstance(evt3, ToolCallDTO)
    assert evt3.tool_name == "grep"
    assert evt3.args == {"q": "foo"}
    assert evt3.call_id == "call_101"


def test_parse_event_dto_tool_result():
    # short form
    evt = parse_event_dto(("tool_result", "output text", ""))
    assert isinstance(evt, ToolResultDTO)
    assert evt.content == "output text"
    assert not evt.is_error
    assert evt.status == "done"
    assert evt.returncode is None

    # full form
    evt2 = parse_event_dto(("tool_result", "error occurred", "bash", True, "failed", 1, "call_1"))
    assert isinstance(evt2, ToolResultDTO)
    assert evt2.content == "error occurred"
    assert evt2.tool_name == "bash"
    assert evt2.is_error is True
    assert evt2.status == "failed"
    assert evt2.returncode == 1


def test_parse_event_dto_compaction():
    evt = parse_event_dto(("compaction", "Summary of conversation"))
    assert isinstance(evt, CompactionEventDTO)
    assert evt.summary == "Summary of conversation"

    evt2 = parse_event_dto(("event_divider", "Session Compacted"))
    assert isinstance(evt2, CompactionEventDTO)
    assert evt2.summary == "Session Compacted"


def test_parse_event_dto_turn_completed():
    evt = parse_event_dto(("turn_completed", 2.5, {"prompt_tokens": 150}))
    assert isinstance(evt, TurnCompletedDTO)
    assert evt.duration_s == 2.5
    assert evt.usage == {"prompt_tokens": 150}


def test_parse_event_dto_error():
    evt = parse_event_dto(("error", "Something went wrong", True))
    assert isinstance(evt, ErrorEventDTO)
    assert evt.message == "Something went wrong"
    assert evt.fatal is True


def test_parse_event_dto_invalid():
    with pytest.raises(ValueError, match="Empty stream step"):
        parse_event_dto(())

    with pytest.raises(ValueError, match="Unknown stream event type"):
        parse_event_dto(("unrecognized_event", "foo"))


def test_session_dtos():
    summary = SessionSummaryDTO(
        id="s1",
        title="Session 1",
        created_at=100.0,
        updated_at=200.0,
        message_count=5,
        token_count=1000,
    )
    assert summary.id == "s1"
    assert summary.message_count == 5

    msg = MessageDTO(role="user", content="hello", timestamp=100.0)
    assert msg.role == "user"
    assert msg.tool_calls == []
    assert msg.attachments == []

    session = SessionDTO(id="s1", title="Session 1", created_at=100.0, updated_at=200.0, messages=[msg])
    assert len(session.messages) == 1


def test_rewind_point_dto():
    rp = RewindPointDTO(
        index=3,
        text="edit main.py",
        insertions=12,
        deletions=4,
        changed_files=("main.py", "app.py"),
        is_checkpoint_available=True,
    )
    assert rp.index == 3
    assert rp.insertions == 12
    assert rp.deletions == 4
    assert rp.changed_files == ("main.py", "app.py")
    assert rp.is_checkpoint_available is True

    # default values
    rp_default = RewindPointDTO(index=0, text="init")
    assert rp_default.insertions == 0
    assert rp_default.deletions == 0
    assert rp_default.changed_files == ()
    assert rp_default.is_checkpoint_available is True


def test_provider_dtos():
    model = ModelInfoDTO(
        name="gpt-4o",
        display_name="GPT-4o",
        provider="openai",
        context_window=128000,
        supports_vision=True,
        supports_thinking=False,
    )
    assert model.name == "gpt-4o"
    assert model.supports_vision is True

    provider = ProviderDTO(name="openai", is_configured=True, models=[model])
    assert provider.name == "openai"
    assert provider.is_configured is True
    assert len(provider.models) == 1


def test_system_dtos():
    skill = SkillDTO(name="test_skill", description="A skill", path="/skills/test.md")
    assert skill.enabled is True
    assert skill.is_project is False

    rule = RuleDTO(title="No pip", path="/rules/pip.md", content_preview="Use uv", scope="global")
    assert rule.title == "No pip"

    task = TaskDTO(task_id="t1", command="ls", status="running")
    assert task.returncode is None
    assert task.log_path == ""

    git = GitStateDTO(branch="main", is_dirty=True, changed_files=2)
    assert git.branch == "main"
    assert git.is_dirty is True
    assert git.changed_files == 2

    perm = PermissionRequestDTO(tool_name="bash", args={"command": "rm -rf /"}, risk_level="high")
    assert perm.risk_level == "high"
    assert perm.reason == ""


def test_commands_dtos():
    comp = CompactionResultDTO(success=True, tokens_before=1000, tokens_after=200, summary="done")
    assert comp.success is True
    assert comp.tokens_before == 1000
    assert comp.tokens_after == 200
    assert comp.error is None

    cmd = CommandResultDTO(name="/compact", success=True, message="Compacted")
    assert cmd.name == "/compact"
    assert cmd.success is True
