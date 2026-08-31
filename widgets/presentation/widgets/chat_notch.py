"""Top Dynamic Island / Floating Toast widget."""
from __future__ import annotations

from rich.text import Text
from textual.containers import Container
from textual.widgets import Static


class ChatNotch(Static):
    """Inner notch pill styled like a toast."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.status_text: str = "Ready"

    def on_mount(self) -> None:
        self.refresh_notch()

    def set_status(self, text: str) -> None:
        self.status_text = text
        self.refresh_notch()

    def refresh_notch(self) -> None:
        try:
            from widgets.app.theme_manager import theme_manager

            t = theme_manager.current_theme
            primary, muted, secondary = t.primary, t.muted, t.secondary
        except Exception:
            primary, muted, secondary = "#ffffff", "#71717a", "#a1a1aa"

        try:
            app = self.app
            role = getattr(app, "role", "worker")
        except Exception:
            role = "worker"

        status = self.status_text

        content = Text()
        content.append("● ", style="bold green" if status == "Ready" else "bold yellow")
        content.append("johnston", style=f"bold {primary}")
        content.append(" │ ", style=muted)
        content.append(f"{role}", style=secondary)
        content.append(" │ ", style=muted)
        content.append(f"{status}", style=muted)

        try:
            self.update(content)
        except Exception:
            pass


class ChatNotchContainer(Container):
    """Overlay container that anchors the floating notch at the top center."""

    can_focus = False
    ALLOW_SELECT = False

    def compose(self):
        yield ChatNotch(id="chat-notch")


class HudOverlay(Container):
    """Overlay container for floating HUD elements (header notch and footer)."""

    can_focus = False
    ALLOW_SELECT = False
