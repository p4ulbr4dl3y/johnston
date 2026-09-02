from importlib.metadata import PackageNotFoundError, version

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from widgets.utils.responsive import BREAKPOINT_BANNER, is_compact_width, resolve_width


def _app_version() -> str:
    """Installed version, or an empty string when running from a bare checkout."""
    try:
        return version("johnston")
    except (PackageNotFoundError, Exception):  # noqa: B014 - broad: never break startup
        return ""


class WelcomeWidget(Vertical):
    """Welcome logo on the main screen with version, connection and first-run tips.

    The empty chat is the only moment the app gets to teach itself, so it shows
    what the footer cannot: which version is running, which provider/model is
    wired up, and the three or four keys that unlock everything else (P2-10).
    """

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

    # (key, what it does) — shown as a two-column block under the logo.
    TIPS: tuple[tuple[str, str], ...] = (
        ("/help", "commands and key bindings"),
        ("@file", "attach a file to a message"),
        ("ctrl+o", "expand the last tool output"),
        ("ctrl+c", "quit"),
    )

    def compose(self) -> ComposeResult:
        yield Static(self.FULL_BANNER, id="welcome-logo")
        yield Static("", id="welcome-tagline")
        yield Static("", id="welcome-tips")

    # -- content ---------------------------------------------------------
    def _connection_line(self) -> str:
        """`Claude Sonnet 4.5 via Anthropic`, or a pointer to /providers."""
        try:
            from core.models_catalog import catalog

            pm = getattr(self.app, "pm", None)
            key = pm.get_active_provider_key() if pm is not None else ""
            model = getattr(getattr(self.app, "agent", None), "model", "")
            name = catalog.get_model_display_name(key, model) if key else ""
            if pm is not None and key and not pm.is_provider_connected(key):
                return f"[{key}] not connected — /providers"
            provider = (key or "").capitalize()
            if name and provider:
                return f"{name} via {provider}"
            return "no provider configured — /providers"
        except Exception:
            return ""

    def _tagline_text(self, width: int = 0) -> str:
        parts = []
        app_version = _app_version()
        if app_version:
            parts.append(f"v{app_version}")
        connection = self._connection_line()
        if connection:
            parts.append(connection)
        text = "  •  ".join(parts)
        # A long model name must not wrap into the logo on a narrow terminal.
        if width and len(text) > width:
            text = text[: max(1, width - 1)] + "…"
        return text

    def _tips_text(self, width: int = 0) -> str:
        """Key/description lines padded to a common width.

        Textual does not centre an auto-width child inside a container
        (`align` has no effect on it), so the block is rendered full width with
        `text-align: center` and every line is padded to the same length —
        which centres the block while keeping the keys column aligned.
        """
        gap = max(len(key) for key, _ in self.TIPS) + 2
        lines = [f"{key.ljust(gap)}{what}" for key, what in self.TIPS]
        longest = max(len(line) for line in lines)
        if width > longest:
            lines = [line.ljust(longest) for line in lines]
        return "\n".join(lines)

    # -- responsive ---------------------------------------------------------
    def _update_banner_for_size(self, width: int) -> None:
        try:
            logo = self.query_one("#welcome-logo", Static)
            compact = is_compact_width(width, breakpoint=BREAKPOINT_BANNER)
            logo.update("[bold]johnston[/bold]" if compact else self.FULL_BANNER)

            tagline = self.query_one("#welcome-tagline", Static)
            tagline.update(self._tagline_text(width))

            # Tips only when the block fits without wrapping (P2-10).
            tips = self.query_one("#welcome-tips", Static)
            tips.display = not compact
            if tips.display:
                tips.update(self._tips_text(width))
        except Exception:
            pass

    def on_mount(self) -> None:
        self._update_banner_for_size(resolve_width(self))

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
