"""App (state/composition) layer for UI widgets.

This package holds state-building / data-aggregation helpers that widgets
delegate to, keeping widgets focused on rendering. Modules here may read
``self.app.*`` / import core freely.
"""
__all__ = ["JohnstonApp"]


def __getattr__(name: str):
    if name == "JohnstonApp":
        from johnston.tui.app.app import JohnstonApp

        return JohnstonApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

