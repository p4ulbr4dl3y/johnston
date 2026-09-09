"""Core interfaces package."""
from __future__ import annotations

from core.interfaces.host import HostProtocol, NullHost

__all__ = [
    "HostProtocol",
    "NullHost",
]
