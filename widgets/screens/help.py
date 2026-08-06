from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown

COMMANDS_MD = """### **[ Commands ]** &nbsp;&nbsp;&nbsp;&nbsp; Keybindings

* `/connect` — Connect AI provider & set API key
* `/models` — Switch active model across providers
* `/thinking` — Set reasoning effort / thinking budget
* `/new` — Start a new chat session
* `/compact` — Compact session conversation history
* `/subagents` — View and manage active subagents
* `/tasks` — View and manage background tasks
* `/skills` — Browse and activate available skills
* `/mcp` — Manage MCP servers (eager / lazy)
* `/rewind` — Rollback chat history to a selected message
* `/resume` — Switch and resume saved session dialogs
* `/help` — Open this help screen"""

KEYBINDINGS_MD = """### &nbsp;&nbsp; Commands &nbsp;&nbsp;&nbsp;&nbsp; **[ Keybindings ]**

* `Shift+Tab` — Toggle Action / Explore mode
* `Ctrl+B` — Move active shell tasks to background
* `Ctrl+O` — Expand / collapse tool output & thinking
* `Enter` — Send message
* `Ctrl+Enter` / `Shift+Enter` — Insert new line in input
* `Ctrl+V` — Paste text or clipboard image
* `Ctrl+D` — Detach attached clipboard images
* `↑` / `↓` — History navigation (looping)
* `@` — Attach workspace file (autocompletion)
* `Esc` — Cancel response generation / Close modals
* `Ctrl+C` / `Ctrl+Q` — Exit application"""


class HelpScreen(ModalScreen[None]):
    """Modal help screen with 2 tabs: Commands & Keybindings"""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "close", "Close"),
        ("enter", "close", "Close"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self):
        super().__init__()
        self.active_tab = 0  # 0: Commands, 1: Keybindings

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(COMMANDS_MD, id="help-markdown", classes="modal-markdown")
            yield Label("tab / ←/→: switch • esc: cancel", id="modal-hint")

    async def _on_key(self, event: events.Key) -> None:
        if event.key in ("left", "right", "tab", "backtab"):
            self.active_tab = 1 if self.active_tab == 0 else 0
            md_widget = self.query_one("#help-markdown", Markdown)
            md_widget.update(KEYBINDINGS_MD if self.active_tab == 1 else COMMANDS_MD)
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)


    def action_close(self) -> None:
        self.dismiss(None)

