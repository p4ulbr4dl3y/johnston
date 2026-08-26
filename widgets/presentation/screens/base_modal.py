from typing import TypeVar

from textual.screen import ModalScreen

from widgets.utils.key_aliases import expand_bindings

T = TypeVar("T")


STATUS_TAG_MAP = {
    "ACTIVE": "●",
    "ON": "●",
    "OFF": "○",
    "AUTH": " ",
    "ERR": "▲",
    "VISIBLE": "●",
    "HIDDEN": "○",
    "LOCKED": "◆",
}


def status_tag(mode: str) -> str:
    """Returns clean Unicode status indicator for OptionList items."""
    clean = str(mode).strip("[]").upper()
    return STATUS_TAG_MAP.get(clean, clean)


class BaseModalScreen(ModalScreen[T]):
    """Base class for all Johnston modal screens with standard exit keybindings."""

    ALLOW_SELECT = False
    inherit_bindings = False
    BINDINGS = expand_bindings([
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def dismiss(self, result: T = None) -> None:
        try:
            if getattr(self, "_is_dismissed", False):
                return
            app = None
            try:
                app = self.app
            except Exception:
                app = getattr(self, "_app", None)
            if app is not None:
                stack = getattr(app, "_screen_stack", [])
                if len(stack) <= 1 or not any(x is self for x in stack):
                    return
            self._is_dismissed = True
            super().dismiss(result)
        except Exception:
            pass
