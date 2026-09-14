"""DTO <-> plain-dict codec for JSON-RPC transport.

Serializes the frozen, slots=True dataclasses from ``johnston.core.dto`` into
plain JSON-friendly dicts and reconstructs them back.  Every serialized dict
carries a ``_type`` discriminator key naming the concrete class; dicts without
one (legacy payloads) are matched by field names.
"""

from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass
from typing import Any, get_type_hints

from johnston.core.dto import (
    CommandResultDTO,
    CompactionEventDTO,
    CompactionResultDTO,
    ContentDeltaDTO,
    ErrorEventDTO,
    FooterCacheDTO,
    GitDiffDTO,
    GitStateDTO,
    MessageDTO,
    ModelInfoDTO,
    PermissionRequestDTO,
    ProviderDTO,
    QueuedUserMessageDTO,
    RetryEventDTO,
    RewindPointDTO,
    RoleInfoDTO,
    RuleDTO,
    SessionDTO,
    SessionSnapshotDTO,
    SessionSummaryDTO,
    SkillDTO,
    StatusFooterDTO,
    StreamEventDTO,
    TaskDTO,
    ThinkingDeltaDTO,
    ToolCallDTO,
    ToolResultDTO,
    TurnCompletedDTO,
    WorkspaceRootDTO,
    WorktreeDTO,
)

__all__ = [
    "DTO_TYPE_MAP",
    "EVENT_TYPE_MAP",
    "deserialize_event",
    "dict_to_dto",
    "dto_to_dict",
    "serialize_event",
]

_TYPE_KEY = "_type"

# StreamEventDTO subclasses, listed so events are preferred during legacy
# field-name matching over the bare base class / unrelated DTOs.
_EVENT_SUBCLASSES: tuple[type[StreamEventDTO], ...] = (
    CompactionEventDTO,
    ContentDeltaDTO,
    ErrorEventDTO,
    QueuedUserMessageDTO,
    RetryEventDTO,
    ThinkingDeltaDTO,
    ToolCallDTO,
    ToolResultDTO,
    TurnCompletedDTO,
)

_ALL_DTO_CLASSES: tuple[type, ...] = _EVENT_SUBCLASSES + (
    CommandResultDTO,
    CompactionResultDTO,
    FooterCacheDTO,
    GitDiffDTO,
    GitStateDTO,
    MessageDTO,
    ModelInfoDTO,
    PermissionRequestDTO,
    ProviderDTO,
    RewindPointDTO,
    RoleInfoDTO,
    RuleDTO,
    SessionDTO,
    SessionSnapshotDTO,
    SessionSummaryDTO,
    SkillDTO,
    StatusFooterDTO,
    TaskDTO,
    WorkspaceRootDTO,
    WorktreeDTO,
    StreamEventDTO,
)

DTO_TYPE_MAP: dict[str, type] = {cls.__name__: cls for cls in _ALL_DTO_CLASSES}
EVENT_TYPE_MAP: dict[str, type[StreamEventDTO]] = {cls.__name__: cls for cls in _EVENT_SUBCLASSES}

_HINTS_CACHE: dict[type, dict[str, Any]] = {}


def _field_hints(cls: type) -> dict[str, Any]:
    """Resolved (non-string) type annotations for ``cls``, cached."""
    hints = _HINTS_CACHE.get(cls)
    if hints is None:
        hints = get_type_hints(cls)
        _HINTS_CACHE[cls] = hints
    return hints


def _is_dto_type(hint: Any) -> bool:
    return isinstance(hint, type) and is_dataclass(hint)


def _is_tuple_type(hint: Any) -> bool:
    origin = getattr(hint, "__origin__", None)
    return hint is tuple or origin is tuple


def _list_item_hint(hint: Any) -> Any:
    origin = getattr(hint, "__origin__", None)
    if hint is list or origin is list:
        args = getattr(hint, "__args__", ())
        return args[0] if args else Any
    return None


def dto_to_dict(obj: Any) -> Any:
    """Recursively convert a DTO instance to plain, JSON-serializable data.

    - dataclass -> dict of its fields plus a ``_type`` class-name key
    - tuple/list -> list of recursively converted elements
    - dict -> dict with recursively converted values
    - primitives pass through unchanged
    - None field values are skipped to keep payloads small
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        out: dict[str, Any] = {_TYPE_KEY: type(obj).__name__}
        for f in fields(obj):
            # slots=True dataclasses: never access __dict__.
            value = getattr(obj, f.name)
            if value is None:
                continue
            out[f.name] = dto_to_dict(value)
        return out
    if isinstance(obj, (tuple, list)):
        return [dto_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: dto_to_dict(v) for k, v in obj.items()}
    return obj


def _convert_value(value: Any, hint: Any) -> Any:
    """Recursively convert one field value, guided by its type annotation."""
    if isinstance(value, dict):
        if _is_dto_type(hint):
            return dict_to_dto(value)
        return {k: _convert_value(v, Any) for k, v in value.items()}
    if isinstance(value, list):
        item_hint = _list_item_hint(hint)
        return [_convert_value(item, item_hint) for item in value]
    if isinstance(value, tuple):
        return [_convert_value(item, Any) for item in value]
    return value


def _match_by_fields(data: dict[str, Any]) -> type | None:
    """Best-effort class lookup for legacy dicts without a ``_type`` key.

    A class qualifies when every key is a known field name and all its
    required (default-less) fields are present; the class covering the most
    keys wins.  Returns None when nothing plausibly matches.
    """
    best: type | None = None
    best_score = -1
    for cls in _ALL_DTO_CLASSES:
        cls_fields = fields(cls)
        names = {f.name for f in cls_fields}
        if not data.keys() <= names:
            continue
        if any(
            f.name not in data
            for f in cls_fields
            if f.default is MISSING and f.default_factory is MISSING
        ):
            continue
        score = len(data)
        if score > best_score:
            best = cls
            best_score = score
    return best


def dict_to_dto(data: dict[str, Any]) -> Any:
    """Reconstruct a DTO from a dict produced by ``dto_to_dict``.

    ``_type`` selects the concrete class; legacy dicts without ``_type`` are
    matched by field names.  Unknown/extra fields are silently ignored for
    forward compatibility.  If nothing matches, ``data`` is returned
    unchanged.
    """
    if not isinstance(data, dict):
        return data
    cls = DTO_TYPE_MAP.get(data.get(_TYPE_KEY))
    if cls is None:
        cls = _match_by_fields(data)
    if cls is None:
        return data
    hints = _field_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        hint = hints.get(f.name, Any)
        value = _convert_value(data[f.name], hint)
        if isinstance(value, list) and _is_tuple_type(hint):
            value = tuple(value)
        kwargs[f.name] = value
    return cls(**kwargs)


def serialize_event(event: StreamEventDTO) -> dict[str, Any]:
    """Serialize a single StreamEventDTO for JSON-RPC notification params.

    Returns the flat dict produced by ``dto_to_dict`` (no wrapping).
    """
    data = dto_to_dict(event)
    assert isinstance(data, dict), "dto_to_dict must return a dict for dataclasses"
    return data


def deserialize_event(data: dict[str, Any]) -> StreamEventDTO:
    """Deserialize a dict back into a StreamEventDTO subclass.

    Uses the ``_type`` discriminator produced by ``dto_to_dict``.
    """
    dto = dict_to_dto(data)
    if not isinstance(dto, StreamEventDTO):
        raise ValueError(f"Not a serialized StreamEventDTO: {data!r}")
    return dto
