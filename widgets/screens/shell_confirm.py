from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown


from core.platform_utils import is_windows


class ShellConfirmScreen(ModalScreen[bool]):
    """Modal screen for requesting permission to run a potentially dangerous shell command across Windows, macOS, and Linux."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("enter", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "quit", "Exit"),
        ("ctrl+q", "quit", "Exit"),
    ]

    def __init__(self, command: str, reason: str = ""):
        super().__init__()
        self.command = command
        self.reason = reason

    def compose(self) -> ComposeResult:
        lang = "powershell" if is_windows() else "bash"
        content = (
            "### **Confirm Shell Command**\n"
            f"```{lang}\n"
            f"{self.command}\n"
            "```"
        )
        with Vertical(id="modal-dialog", classes="bash-confirm-dialog"):
            yield Markdown(content, classes="modal-markdown")
            yield Label("enter: confirm • esc: cancel", id="modal-hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_quit(self) -> None:
        self.app.exit()
