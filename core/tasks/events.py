"""TaskEvents: single integration point for task completion side-effects.

Centralizes where completion metrics (merge_subagent_metrics) and notifications
get emitted, so the rest of the codebase calls one hook instead of duplicating
the wiring. Currently a pure structure — invocation from existing callers is
added in a later refactor step.
"""

from typing import Any, Optional


class TaskEvents:
    """Collects completion hooks; currently a lightweight registry.

    ``on_completed`` deliberately does nothing beyond dispatching to registered
    handlers so it is safe to call even before any hook is wired in.
    """

    def __init__(self, app: Any = None, sm: Any = None) -> None:
        self.app = app
        self.sm = sm
        self._handlers = []

    def add_handler(self, fn: Any) -> None:
        if fn not in self._handlers:
            self._handlers.append(fn)

    def on_completed(self, task: Any, result: str = "", error: Optional[str] = None) -> None:
        """Dispatch a single 'task completed' event to registered handlers."""
        for fn in list(self._handlers):
            try:
                fn(task, result, error)
            except Exception:
                pass
