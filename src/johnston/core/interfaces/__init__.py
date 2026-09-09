"""Core interfaces package."""
from __future__ import annotations

from johnston.core.interfaces.host import (
    ExecutionObserverHost,
    HostProtocol,
    NullHost,
    ShellTaskHost,
    UserInteractionHost,
)

__all__ = [
    "ExecutionObserverHost",
    "HostProtocol",
    "NullHost",
    "ShellTaskHost",
    "UserInteractionHost",
]
