"""App (state/composition) layer for UI widgets.

This package holds state-building / data-aggregation helpers that widgets
delegate to, keeping widgets focused on rendering. Modules here may read
``self.app.*`` / import core freely.
"""
__all__ = [
    "AppLifecycleService",
    "JohnstonApp",
    "SessionPersistenceService",
    "TaskWidgetRegistry",
    "UserInteractionService",
]


def __getattr__(name: str):
    if name == "AppLifecycleService":
        from johnston.tui.app.lifecycle_service import AppLifecycleService

        return AppLifecycleService
    if name == "JohnstonApp":
        from johnston.tui.app.app import JohnstonApp

        return JohnstonApp
    if name == "SessionPersistenceService":
        from johnston.tui.app.session_service import SessionPersistenceService

        return SessionPersistenceService
    if name == "TaskWidgetRegistry":
        from johnston.tui.app.task_registry import TaskWidgetRegistry

        return TaskWidgetRegistry
    if name == "UserInteractionService":
        from johnston.tui.app.interaction_service import UserInteractionService

        return UserInteractionService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

