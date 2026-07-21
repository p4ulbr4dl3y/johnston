from typing import TypeVar, Generic
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import OptionList, Markdown, Input, Label
from textual import events

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


class QuestionScreen(ModalScreen[dict]):
    """Модальное окно для выбора вариантов или текстового ввода без кнопок"""
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("left", "go_back", "Back"),
        ("right", "go_next", "Next"),
        ("ctrl+c", "quit", "Exit"),
    ]

    def __init__(self, num_text: str, question_text: str, options: list[str], current_val: str = ""):
        super().__init__()
        self.num_text = num_text
        self.question_text = question_text
        self.title = f"{num_text}\n\n{question_text}"
        self.raw_options = options
        self.options = options + ["Write-in..."]
        self.current_val = current_val

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self.title, classes="modal-markdown")
            yield OptionList(id="options-list")
            yield Input(placeholder="Type custom response here and press Enter...", id="write-in-input")

    def on_mount(self) -> None:
        try:
            input_field = self.query_one("#write-in-input", Input)
            input_field.display = False
        except Exception:
            pass
        
        opt_list = self.query_one("#options-list", OptionList)
        opt_list.clear_options()
        for opt in self.options:
            opt_list.add_option(opt)
            
        highlight_idx = 0
        if self.current_val:
            if self.current_val in self.raw_options:
                highlight_idx = self.raw_options.index(self.current_val)
            else:
                highlight_idx = len(self.options) - 1
                try:
                    input_field = self.query_one("#write-in-input", Input)
                    input_field.value = self.current_val
                    input_field.display = True
                except Exception:
                    pass
                    
        opt_list.highlighted = highlight_idx
        
        if highlight_idx == len(self.options) - 1:
            try:
                self.query_one("#write-in-input", Input).focus()
            except Exception:
                opt_list.focus()
        else:
            opt_list.focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if not self.is_mounted:
            return
        try:
            input_field = self.query_one("#write-in-input", Input)
            if event.option_index == len(self.options) - 1:
                input_field.display = True
                input_field.focus()
            else:
                input_field.display = False
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        try:
            if event.option_index != len(self.options) - 1:
                self.submit_answer()
            else:
                self.query_one("#write-in-input", Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.submit_answer()

    def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            try:
                input_field = self.query_one("#write-in-input", Input)
                if self.focused is input_field:
                    opt_list = self.query_one("#options-list", OptionList)
                    opt_list.highlighted = len(self.options) - 2
                    opt_list.focus()
                    event.stop()
            except Exception:
                pass

    def action_cancel(self) -> None:
        self.dismiss({"status": "cancelled", "answer": "Cancelled"})

    def action_go_back(self) -> None:
        if self.focused is not self.query_one("#write-in-input"):
            self.dismiss({"status": "back", "answer": ""})

    def action_go_next(self) -> None:
        if self.focused is not self.query_one("#write-in-input"):
            self.submit_answer(status="next")

    def action_quit(self) -> None:
        self.app.exit()

    def submit_answer(self, status: str = "next") -> None:
        try:
            opt_list = self.query_one("#options-list", OptionList)
            idx = opt_list.highlighted
            
            if idx == len(self.options) - 1:
                val = self.query_one("#write-in-input", Input).value.strip()
                answer = val if val else "Custom answer"
            else:
                answer = self.options[idx] if idx is not None else ""
                
            self.dismiss({"status": status, "answer": answer})
        except Exception as e:
            self.dismiss({"status": "error", "answer": f"Error: {e}"})


class ConfirmScreen(ModalScreen[str]):
    """Модальное окно подтверждения ответов перед отправкой без подсказок"""
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("left", "go_back", "Back"),
        ("enter", "confirm", "Confirm"),
        ("ctrl+c", "quit", "Exit"),
    ]

    def __init__(self, summary: str):
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Подтвердите ваши ответы**\n\n" + self.summary, classes="modal-markdown")

    def action_confirm(self) -> None:
        self.dismiss("confirm")

    def action_go_back(self) -> None:
        self.dismiss("back")

    def action_cancel(self) -> None:
        self.dismiss("cancelled")

    def action_quit(self) -> None:
        self.app.exit()
