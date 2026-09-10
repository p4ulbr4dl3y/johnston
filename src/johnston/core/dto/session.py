from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class SessionSummaryDTO:
    id: str
    title: str
    created_at: float
    updated_at: float
    message_count: int
    token_count: int


@dataclass(slots=True, frozen=True)
class MessageDTO:
    role: str
    content: str
    timestamp: float
    tool_calls: list[Any] = field(default_factory=list)
    attachments: list[Any] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SessionDTO:
    id: str
    title: str
    created_at: float
    updated_at: float
    messages: list[Any] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class RewindPointDTO:
    index: int
    text: str
    insertions: int = 0
    deletions: int = 0
    changed_files: tuple[str, ...] = ()
    is_checkpoint_available: bool = True
