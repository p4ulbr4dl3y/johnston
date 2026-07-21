from typing import TypeVar, Generic
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import OptionList, Markdown, Input

T = TypeVar("T")

class BaseSelectionScreen(ModalScreen[T], Generic[T]):
    """Базовый класс для модальных окон выбора с OptionList"""
    
    BINDINGS = [("escape", "cancel", "Cancel")]
    
    def __init__(self, title: str, options: list[str], items: list[T], default_value: T):
        super().__init__()
        self.title = title
        self.options = options
        self.items = items
        self.default_value = default_value

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self.title, classes="modal-markdown")
            yield OptionList(*self.options)

    def action_cancel(self) -> None:
        self.dismiss(self.default_value)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.items):
            self.dismiss(self.items[event.option_index])
        else:
            self.dismiss(self.default_value)


class HelpScreen(ModalScreen[None]):
    """Modal help screen (/help)"""
    
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


class RewindScreen(BaseSelectionScreen[int]):
    """Modal rollback screen (/rewind)"""

    def __init__(self, user_messages: list[tuple[int, str]]):
        options = [
            f"{i+1}. {text[:50]}..." if len(text) > 50 else f"{i+1}. {text}"
            for i, (_, text) in enumerate(user_messages)
        ]
        items = [idx for idx, _ in user_messages]
        super().__init__(
            title="### ↺ **Select message to rollback to**",
            options=options,
            items=items,
            default_value=-1
        )


class ResumeScreen(BaseSelectionScreen[str]):
    """Modal session resume screen (/resume)"""

    def __init__(self, sessions: list[dict]):
        options = [
            f"{s['title']} ({s['message_count']} msgs)"
            for s in sessions
        ]
        items = [s["id"] for s in sessions]
        super().__init__(
            title="### **Select session to resume (/resume)**",
            options=options,
            items=items,
            default_value=""
        )


class ProviderScreen(BaseSelectionScreen[str]):
    """Modal provider selection screen (/provider)"""

    def __init__(self, providers: dict):
        providers_list = list(providers.values())
        options = [
            f"{p['name']}" + (f" — {p['description']}" if p.get('description') else "")
            for p in providers_list
        ]
        items = [p["key"] for p in providers_list]
        super().__init__(
            title="### **Select AI provider (/provider)**",
            options=options,
            items=items,
            default_value=""
        )


class ModelScreen(BaseSelectionScreen[str]):
    """Modal model selection screen (/models)"""

    def __init__(self, models: list[str], current_model: str = ""):
        options = [
            f"{'▶ ' if m == current_model else '  '}{m}"
            for m in models
        ]
        super().__init__(
            title="### **Select provider model (/models)**",
            options=options,
            items=models,
            default_value=""
        )


class AskUserScreen(ModalScreen[str]):
    """Modal screen for AskUser tool to prompt user for input"""
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(f"### **Question from Agent:**\n\n{self.question}", classes="modal-markdown")
            yield Input(placeholder="Type your answer and press Enter...", id="ask-user-input")

    def on_mount(self) -> None:
        self.query_one("#ask-user-input").focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss("")
