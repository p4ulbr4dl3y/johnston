from typing import TypeVar

from textual.screen import ModalScreen

T = TypeVar("T")


def status_tag(mode: str) -> str:
    r"""Escapes status tag brackets for Textual markup, e.g. 'ON' -> r'\[ON]'."""
    clean = str(mode).strip("[]").upper()
    return rf"\[{clean}]"


class BaseModalScreen(ModalScreen[T]):
    """Base class for all Johnston modal screens with standard exit keybindings."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_quit(self) -> None:
        self.app.exit()

    def action_cancel(self) -> None:
        self.dismiss(None)
