from typing import TypeVar

from textual.screen import ModalScreen

from widgets.utils.key_aliases import expand_bindings

T = TypeVar("T")


STATUS_TAG_MAP = {
    "ACTIVE": "●",
    "ON": "●",
    "OFF": "○",
    "ALLOW": "✓",
    "DENY": "✕",
    "ASK": "?",
    "AUTH": " ",
    "ERR": "▲",
    "VISIBLE": "●",
    "HIDDEN": "○",
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
