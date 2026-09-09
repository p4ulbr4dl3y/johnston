"""Event dataclasses for the REPL streaming engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class ReplEvent:
    """Base class for all REPL streaming events."""
    pass


@dataclass
class ThinkingStartEvent(ReplEvent):
    """Fired when model begins reasoning/thinking."""
    pass


@dataclass
class ThinkingDoneEvent(ReplEvent):
    """Fired when reasoning completes."""
    duration_s: float
    token_count: int = 0
    content: Optional[str] = None


@dataclass
class ToolCallStartEvent(ReplEvent):
    """Fired when tool execution starts."""
    tool_name: str
    tool_args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallResultEvent(ReplEvent):
    """Fired when tool execution finishes."""
    tool_name: str
    target: str = ""
    summary: str = ""
    diff: Optional[str] = None
    is_error: bool = False
    exit_code: Optional[int] = None


@dataclass
class TextChunkEvent(ReplEvent):
    """Fired when streaming text tokens to stdout."""
    text: str


@dataclass
class TurnDoneEvent(ReplEvent):
    """Fired when turn finishes."""
    total_tokens: int = 0
    added_tokens: int = 0
    estimated_cost_usd: float = 0.0
