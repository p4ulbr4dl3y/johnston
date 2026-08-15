from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class WelcomeWidget(Vertical):
    """Centered welcome logo on main screen"""

    can_focus = False
    ALLOW_SELECT = False

    FULL_BANNER = (
        "   _       _                 _                 \n"
        "  (_)     | |               | |                \n"
        "   _  ___ | |__  _ __  ___ _| |_ ___  _ __     \n"
        "  | |/ _ \\| '_ \\| '_ \\/ __|_   _/ _ \\| '_ \\    \n"
        "  | | (_) | | | | | | \\__ \\ | || (_) | | | |   \n"
        "  | |\\___/|_| |_|_| |_|___/  \\__\\___/|_| |_|   \n"
        " /_/                                           "
    )

    def compose(self) -> ComposeResult:
        yield Static(self.FULL_BANNER, id="welcome-logo")

    def _update_banner_for_size(self, width: int) -> None:
        try:
            logo = self.query_one("#welcome-logo", Static)
            if width < 52:
                logo.update("[bold #ffffff]johnston[/bold #ffffff]")
            else:
                logo.update(self.FULL_BANNER)
        except Exception:
            pass

    def on_mount(self) -> None:
        if self.app and self.app.size.width > 0:
            self._update_banner_for_size(self.app.size.width)

    def on_resize(self, event) -> None:
        self._update_banner_for_size(event.size.width)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if self.screen:
            self.screen.clear_selection()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self.screen:
            self.screen.clear_selection()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self.screen:
            self.screen.clear_selection()
