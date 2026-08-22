"""Pure session domain constants and trivial helpers.

No IO, no agent access. Imported directly by consumers across core and UI.
"""

from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    """Canonical session lifecycle statuses.

    ``str, Enum`` so the persisted/rendered value is the plain string
    (``.value``) and comparisons against ``str`` literals keep working.
    """

    ACTIVE = "active"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"

    def __str__(self) -> str:
        return self.value


def _coerce_int(val: Any) -> int:
    """Coerce a persisted token count to int, tolerating None/invalid types."""
    if val is None or isinstance(val, bool):
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _coerce_float(val: Any) -> float:
    """Coerce a persisted cost value to float, tolerating None/invalid types."""
    if val is None or isinstance(val, bool):
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

