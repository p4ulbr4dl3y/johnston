from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Markdown


class BashConfirmScreen(ModalScreen[bool]):
    """Modal screen for requesting permission to run a bash command."""

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
        with Vertical(id="modal-dialog"):
            yield Markdown(content, classes="modal-markdown")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_quit(self) -> None:
        self.app.exit()
