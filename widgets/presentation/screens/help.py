from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Markdown

from widgets.presentation.screens.base_modal import BaseModalScreen

COMMANDS_BODY_MD = """* `/connect` — Connect AI provider & set API key
* `/models` — Switch active model across providers
* `/thinking` — Set reasoning effort / thinking budget
* `/new` — Start a new chat session
* `/compact` — Compact session conversation history
* `/subagents` — View and manage subagents
* `/shell` — View and manage background shell tasks
* `/skills` — Browse and activate available skills
* `/mcp` — Manage MCP servers
* `/rewind` — Rollback chat history to a selected message
* `/resume` — Switch and resume saved session dialogs
* `/help` — Open this help screen"""

KEYBINDINGS_BODY_MD = """* `Shift+Tab` — Toggle Action / Explore mode
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


class HelpScreen(BaseModalScreen[None]):
    """Modal help screen with 2 tabs: Commands & Keybindings"""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("enter", "close", "Close"),
    ]

    def __init__(self):
        super().__init__()
        self.active_tab = 0  # 0: Commands, 1: Keybindings

    def _get_header_md(self) -> str:
        t0 = "**[ Commands ]**" if self.active_tab == 0 else "**Commands**"
        t1 = "**[ Keybindings ]**" if self.active_tab == 1 else "**Keybindings**"
        return f"### **Johnston Help**\n{t0} &nbsp;&nbsp;&nbsp;&nbsp; {t1}"

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self._get_header_md(), id="help-header-md", classes="modal-markdown modal-markdown-centered")
            yield Markdown(COMMANDS_BODY_MD, id="help-body-md", classes="modal-markdown")
            yield Label("tab / ←/→: switch • esc: close", id="modal-hint")

    async def _on_key(self, event: events.Key) -> None:
        if event.key in ("left", "right", "tab", "backtab"):
            self.active_tab = 1 if self.active_tab == 0 else 0
            header_md = self.query_one("#help-header-md", Markdown)
            header_md.update(self._get_header_md())
            body_md = self.query_one("#help-body-md", Markdown)
            body_md.update(KEYBINDINGS_BODY_MD if self.active_tab == 1 else COMMANDS_BODY_MD)
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)

    def action_close(self) -> None:
        self.dismiss(None)
