"""App (state/composition) layer for UI widgets.

This package holds state-building / data-aggregation helpers that widgets
delegate to, keeping widgets focused on rendering. Modules here may read
``self.app.*`` / import core freely.
"""

from johnston_tui.app.app import JohnstonApp  # noqa: E402


def main() -> int:
    app = JohnstonApp()
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    return 0


__all__ = ["JohnstonApp", "main"]
