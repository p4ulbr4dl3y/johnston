from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown


class BashConfirmScreen(ModalScreen[bool]):
    """Modal screen for requesting permission to run a bash command."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("enter", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "quit", "Exit"),
    ]

    def __init__(self, command: str, reason: str = ""):
        super().__init__()
        self.command = command
        self.reason = reason

    def compose(self) -> ComposeResult:
        content = (
            "### **Confirm Bash Command**\n\n"
            "```bash\n"
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
