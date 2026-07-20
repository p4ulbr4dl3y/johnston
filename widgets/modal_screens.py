from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import OptionList, Markdown

class HelpScreen(ModalScreen[None]):
    """Modal help screen (/help)"""
    
    BINDINGS = [
        ("escape", "close", "Close"),
        ("enter", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(
                "### 💡 **Command Help**\n\n"
                "* `/help` — Open this help\n"
                "* `/new` — Start a new chat session\n"
                "* `/provider` — Switch AI provider\n"
                "* `/models` — Switch active provider model\n"
                "* `/rewind` — Rollback chat history to a selected message\n"
                "* `/resume` — Switch and resume saved session dialogs\n\n"
                "**Hotkeys:**\n"
                "* `Enter` — Send message\n"
                "* `Ctrl+Enter` / `Shift+Enter` — Insert new line\n"
                "* `↑ / ↓` — History navigation (looping)\n"
                "* `Esc` — Cancel response generation\n"
                "* `Ctrl+C` / `Ctrl+Q` — Exit application",
                classes="modal-markdown"
            )

    def action_close(self) -> None:
        self.dismiss(None)


class RewindScreen(ModalScreen[int]):
    """Modal rollback screen (/rewind)"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, user_messages: list[tuple[int, str]]):
        super().__init__()
        self.user_messages = user_messages

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### ↺ **Select message to rollback to**", classes="modal-markdown")
            
            options = [
                f"{i+1}. {text[:50]}..." if len(text) > 50 else f"{i+1}. {text}"
                for i, (_, text) in enumerate(self.user_messages)
            ]
            yield OptionList(*options, id="rewind-option-list")

    def action_cancel(self) -> None:
        self.dismiss(-1)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        selected_idx = self.user_messages[event.option_index][0]
        self.dismiss(selected_idx)


class ResumeScreen(ModalScreen[str]):
    """Modal session resume screen (/resume)"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, sessions: list[dict]):
        super().__init__()
        self.sessions = sessions

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### 📁 **Select session to resume (/resume)**", classes="modal-markdown")
            
            options = [
                f"💬 {s['title']} ({s['message_count']} msgs)"
                for s in self.sessions
            ]
            yield OptionList(*options, id="resume-session-option-list")

    def action_cancel(self) -> None:
        self.dismiss("")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.sessions):
            selected_session_id = self.sessions[event.option_index]["id"]
            self.dismiss(selected_session_id)
        else:
            self.dismiss("")


class ProviderScreen(ModalScreen[str]):
    """Modal provider selection screen (/provider)"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, providers: dict):
        super().__init__()
        self.providers_list = list(providers.values())

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### 🔌 **Select AI provider (/provider)**", classes="modal-markdown")
            
            options = [
                f"⚡ {p['name']}" + (f" — {p['description']}" if p.get('description') else "")
                for p in self.providers_list
            ]
            yield OptionList(*options, id="provider-option-list")

    def action_cancel(self) -> None:
        self.dismiss("")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.providers_list):
            selected_key = self.providers_list[event.option_index]["key"]
            self.dismiss(selected_key)
        else:
            self.dismiss("")


class ModelScreen(ModalScreen[str]):
    """Modal model selection screen (/models)"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, models: list[str], current_model: str = ""):
        super().__init__()
        self.models = models
        self.current_model = current_model

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### 🤖 **Select provider model (/models)**", classes="modal-markdown")
            
            options = [
                f"{'▶ ' if m == self.current_model else '  '}{m}"
                for m in self.models
            ]
            yield OptionList(*options, id="model-option-list")

    def action_cancel(self) -> None:
        self.dismiss("")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.models):
            selected_model = self.models[event.option_index]
            self.dismiss(selected_model)
        else:
            self.dismiss("")
