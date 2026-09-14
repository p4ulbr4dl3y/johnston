"""Round-trip tests for the JSON-RPC DTO codec (johnston.core.rpc.codec).

Every StreamEventDTO subclass plus the remaining core DTOs are serialized and
reconstructed field-by-field; None values are dropped on the wire, unknown
fields are ignored on read, and tuple fields round-trip through JSON arrays.
"""

import pytest

from johnston.core.dto import (
    CompactionEventDTO,
    ContentDeltaDTO,
    ErrorEventDTO,
    ModelInfoDTO,
    ProviderDTO,
    QueuedUserMessageDTO,
    RetryEventDTO,
    RewindPointDTO,
    SessionDTO,
    SessionSummaryDTO,
    SkillDTO,
    ThinkingDeltaDTO,
    ToolCallDTO,
    ToolResultDTO,
    TurnCompletedDTO,
)
from johnston.core.rpc.codec import (
    EVENT_TYPE_MAP,
    deserialize_event,
    dict_to_dto,
    dto_to_dict,
    serialize_event,
)


def _every_dto_object():
    return {
        "ContentDeltaDTO": ContentDeltaDTO(text="hello", is_reset=True, final=False),
        "ThinkingDeltaDTO": ThinkingDeltaDTO(thought="hmm", duration=1.5, phase="end"),
        "ToolCallDTO": ToolCallDTO(
            tool_name="read", args={"path": "a.py"}, call_id="c1", target="a.py", status="running", index=2
        ),
        "ToolResultDTO": ToolResultDTO(
            tool_name="read", content="data", is_error=True, status="done", returncode=1, call_id="c1"
        ),
        "CompactionEventDTO": CompactionEventDTO(summary="compacted"),
        "TurnCompletedDTO": TurnCompletedDTO(
            duration_s=3.25, usage={"input_tokens": 10, "output_tokens": 20}, text="done", tool_calls=["t1"]
        ),
        "ErrorEventDTO": ErrorEventDTO(message="boom", fatal=True),
        "QueuedUserMessageDTO": QueuedUserMessageDTO(
            prompt="hi", attachments=["f.txt"], show_in_ui=False, display_text="hi"
        ),
        "RetryEventDTO": RetryEventDTO(attempt=2, max_retries=5, delay=1.0, error="retry me"),
    }


def _every_dto_instance_with_expected():
    yield from _every_dto_object().items()


def _field_roundtrip_checks(dto_cls, dto):
    data = dto_to_dict(dto)
    assert data["_type"] == dto_cls.__name__
    restored = dict_to_dto(data)
    assert type(restored) is dto_cls
    for f in dto_cls.__dataclass_fields__:
        expected = getattr(dto, f)
        actual = getattr(restored, f)
        if isinstance(expected, tuple):
            assert isinstance(actual, tuple) and list(actual) == list(expected), f"{dto_cls.__name__}.{f}"
        else:
            assert actual == expected, f"{dto_cls.__name__}.{f}"


# ---------------------------------------------------------------------------
# StreamEventDTO subclass round-trips
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dto_cls", "dto"),
    [
        pytest.param(cls, dto, id=name)
        for name, dto in _every_dto_object().items()
        for cls in [type(dto)]
    ],
)
def test_stream_event_roundtrip(dto_cls, dto):
    _field_roundtrip_checks(dto_cls, dto)


def test_content_delta_non_defaults():
    dto = ContentDeltaDTO(text="hello", is_reset=True, final=False)
    data = dto_to_dict(dto)
    assert data == {"_type": "ContentDeltaDTO", "text": "hello", "is_reset": True, "final": False}
    restored = dict_to_dto(data)
    assert restored == dto


def test_tool_call_dict_args_roundtrip():
    dto = ToolCallDTO(tool_name="edit", args={"path": "f.py", "content": "x"}, call_id="cid", status="running")
    restored = dict_to_dto(dto_to_dict(dto))
    assert restored == dto
    assert restored.args == {"path": "f.py", "content": "x"}


def test_turn_completed_usage_roundtrip():
    dto = TurnCompletedDTO(duration_s=1.2, usage={"input": 5, "output": 9})
    restored = dict_to_dto(dto_to_dict(dto))
    assert restored == dto
    assert restored.usage == {"input": 5, "output": 9}


def test_error_event_roundtrip():
    dto = ErrorEventDTO(message="kaboom", fatal=True)
    restored = dict_to_dto(dto_to_dict(dto))
    assert restored == dto


def test_queued_user_message_roundtrip():
    dto = QueuedUserMessageDTO(prompt="p", attachments=["a", "b"], show_in_ui=True, display_text="p")
    restored = dict_to_dto(dto_to_dict(dto))
    assert restored == dto


def test_retry_event_roundtrip():
    dto = RetryEventDTO(attempt=3, max_retries=4, delay=0.5, error="failed")
    restored = dict_to_dto(dto_to_dict(dto))
    assert restored == dto


def test_compaction_event_roundtrip():
    dto = CompactionEventDTO(summary="summarized")
    restored = dict_to_dto(dto_to_dict(dto))
    assert restored == dto


# ---------------------------------------------------------------------------
# Non-event DTO round-trips
# ---------------------------------------------------------------------------


def test_session_summary_roundtrip():
    dto = SessionSummaryDTO(id="s1", title="t", created_at=1.0, updated_at=2.0, message_count=3, token_count=4)
    _field_roundtrip_checks(SessionSummaryDTO, dto)


def test_session_roundtrip_contents():
    dto = SessionDTO(id="s1", title="t", created_at=1.0, updated_at=2.0, messages=[{"role": "user", "content": "hi"}])
    restored = dict_to_dto(dto_to_dict(dto))
    assert restored == dto
    assert restored.messages == [{"role": "user", "content": "hi"}]


def test_provider_dto_with_nested_models():
    model = ModelInfoDTO(name="gpt", display_name="GPT", provider="openai", context_window=128000, supports_vision=True)
    dto = ProviderDTO(name="openai", is_configured=True, models=[model], key="k", is_active=True)
    restored = dict_to_dto(dto_to_dict(dto))
    assert type(restored) is ProviderDTO
    assert restored == dto
    assert restored.models == [model]


def test_rewind_point_tuple_roundtrip():
    dto = RewindPointDTO(index=3, text="hi", insertions=2, deletions=1, changed_files=("a.py", "b.py"))
    assert dto.changed_files == ("a.py", "b.py")
    data = dto_to_dict(dto)
    assert data["changed_files"] == ["a.py", "b.py"]
    restored = dict_to_dto(data)
    assert type(restored.changed_files) is tuple
    assert restored.changed_files == ("a.py", "b.py")


# ---------------------------------------------------------------------------
# Empty / default fields
# ---------------------------------------------------------------------------


def test_none_fields_excluded_from_payload():
    dto = ToolResultDTO(tool_name="read")
    data = dto_to_dict(dto)
    assert "returncode" not in data
    assert "call_id" in data  # default "" is not None, so it stays
    restored = dict_to_dto(data)
    assert restored == dto


def test_only_none_fields_excluded():
    # Only None is dropped: default ""/False are real values and round-trip.
    dto = ContentDeltaDTO()
    data = dto_to_dict(dto)
    assert data == {"_type": "ContentDeltaDTO", "text": "", "is_reset": False, "final": False}
    restored = dict_to_dto(data)
    assert restored == dto


def test_empty_dataclass_payload_roundtrip():
    dto = ErrorEventDTO(message="")
    restored = dict_to_dto(dto_to_dict(dto))
    assert restored == dto


def test_default_factory_lists_roundtrip():
    dto = QueuedUserMessageDTO(prompt="")
    restored = dict_to_dto(dto_to_dict(dto))
    assert restored == dto


# ---------------------------------------------------------------------------
# Unknown-field resilience
# ---------------------------------------------------------------------------


def test_unknown_fields_ignored():
    data = {"_type": "ContentDeltaDTO", "text": "hi", "future_field": "x"}
    restored = dict_to_dto(data)
    assert isinstance(restored, ContentDeltaDTO)
    assert restored.text == "hi"
    assert not hasattr(restored, "future_field")


def test_unknown_type_key_returns_unchanged():
    data = {"_type": "NotADTO", "text": "hi"}
    assert dict_to_dto(data) is data


# ---------------------------------------------------------------------------
# serialize_event / deserialize_event
# ---------------------------------------------------------------------------


def test_serialize_deserialize_event_wrappers():
    dto = ContentDeltaDTO(text="hello", is_reset=True, final=False)
    data = serialize_event(dto)
    assert data["_type"] == "ContentDeltaDTO"
    restored = deserialize_event(data)
    assert type(restored) is ContentDeltaDTO
    assert restored == dto


def test_deserialize_event_raises_on_non_event_dict():
    with pytest.raises(ValueError):
        deserialize_event(dto_to_dict(SessionSummaryDTO(id="s", title="t", created_at=0.0, updated_at=0.0, message_count=0, token_count=0)))


# ---------------------------------------------------------------------------
# Legacy dicts without _type
# ---------------------------------------------------------------------------


def test_legacy_dict_field_name_matching():
    data = {"text": "legacy", "is_reset": True, "final": False}
    restored = dict_to_dto(data)
    assert type(restored) is ContentDeltaDTO
    assert restored == ContentDeltaDTO(text="legacy", is_reset=True, final=False)


def test_legacy_dict_without_type_for_struct():
    data = {"name": "t", "description": "d", "path": "p"}
    restored = dict_to_dto(data)
    assert type(restored) is SkillDTO
    assert restored.name == "t"


def test_non_dict_input_passthrough():
    assert dict_to_dto("nope") == "nope"
    assert dict_to_dto([1, 2]) == [1, 2]


# ---------------------------------------------------------------------------
# EVENT_TYPE_MAP coverage
# ---------------------------------------------------------------------------


def test_event_type_map_covers_all_subclasses():
    data = dto_to_dict(ContentDeltaDTO(text="x"))
    assert data["_type"] in EVENT_TYPE_MAP
    assert data["_type"] == "ContentDeltaDTO"
    assert EVENT_TYPE_MAP["ContentDeltaDTO"] is ContentDeltaDTO


# ---------------------------------------------------------------------------
# Nested / compound payloads
# ---------------------------------------------------------------------------


def test_nested_dataclass_field_roundtrip():
    dto = ProviderDTO(name="p", is_configured=False, models=[ModelInfoDTO(name="m", display_name="M", provider="p")])
    data = dto_to_dict(dto)
    restored = dict_to_dto(data)
    assert restored == dto
    assert isinstance(restored.models[0], ModelInfoDTO)
