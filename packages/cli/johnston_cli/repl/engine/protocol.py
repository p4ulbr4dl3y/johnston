"""Protocol definition for REPL execution engines."""
from __future__ import annotations

from typing import AsyncIterator, Protocol

from johnston_cli.repl.engine.events import ReplEvent
from johnston_cli.repl.session import ReplSession


class ReplEngine(Protocol):
    """Protocol for asynchronous turn generators."""

    async def generate(
        self,
        prompt: str,
        session: ReplSession,
    ) -> AsyncIterator[ReplEvent]:
        """Generate events for a user prompt."""
        ...
