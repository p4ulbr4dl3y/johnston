from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown


class HelpScreen(ModalScreen[None]):
    """Modal help screen (/help)"""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "close", "Close"),
        ("enter", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(
                "### **Command Help**\n\n"
                "* `/help` — Open this help\n"
                "* `/new` — Start a new chat session\n"
                "* `/connect` — Connect AI provider and set API key\n"
                "* `/models` — Switch active model across providers\n"
                "* `/rewind` — Rollback chat history to a selected message\n"
                "* `/resume` — Switch and resume saved session dialogs\n"
                "* `/tasks` — Manage background tasks\n"
                "* `/subagents` — View and manage subagents\n"
                "* `/skills` — Browse and activate available skills\n"
                "* `/mcp` — Manage MCP servers\n"
                "* `/init` — Guided `AGENTS.md` project setup\n"
                "* `/compact` — Compact session conversation history\n\n"
                "**Hotkeys:**\n"
                "* `Enter` — Send message\n"
                "* `Ctrl+Enter` / `Shift+Enter` — Insert new line\n"
                "* `↑ / ↓` — History navigation (looping)\n"
                "* `Esc` — Cancel response generation\n"
                "* `Ctrl+C` / `Ctrl+Q` — Exit application",
                classes="modal-markdown"
            )
            yield Label("enter / esc: close", id="modal-hint")

    def action_close(self) -> None:
        self.dismiss(None)
