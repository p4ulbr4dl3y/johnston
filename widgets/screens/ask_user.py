from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown, OptionList


class QuestionScreen(ModalScreen[dict]):
    """Modal screen for selecting options or typing custom input without buttons"""
    ALLOW_SELECT = False
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
        self.raw_options = options or []
        self.options = self.raw_options + ["Write-in..."] if self.raw_options else []
        self.current_val = current_val

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self.title, classes="modal-markdown")
            yield OptionList(id="options-list")
            yield Input(placeholder="Type response here and press Enter...", id="write-in-input")
            yield Label("enter: select • ←: back • →: next • esc: cancel", id="modal-hint")

    def on_mount(self) -> None:
        opt_list = self.query_one("#options-list", OptionList)
        input_field = self.query_one("#write-in-input", Input)

        if not self.raw_options:
            opt_list.display = False
            input_field.display = True
            if self.current_val:
                input_field.value = self.current_val
            input_field.focus()
            return

        input_field.display = False
        opt_list.clear_options()
        for opt in self.options:
            opt_list.add_option(opt)

        highlight_idx = 0
        if self.current_val:
            if self.current_val in self.raw_options:
                highlight_idx = self.raw_options.index(self.current_val)
            else:
                highlight_idx = len(self.options) - 1
                input_field.value = self.current_val
                input_field.display = True

        opt_list.highlighted = highlight_idx

        if highlight_idx == len(self.options) - 1:
            input_field.focus()
        else:
            opt_list.focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if not self.is_mounted or not self.raw_options:
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
        if not self.raw_options:
            return
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
        if event.key == "up" and self.raw_options:
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
        if self.focused is not self.query_one("#write-in-input") or not self.raw_options:
            self.dismiss({"status": "back", "answer": ""})

    def action_go_next(self) -> None:
        if self.focused is not self.query_one("#write-in-input") or not self.raw_options:
            self.submit_answer(status="next")

    def action_quit(self) -> None:
        self.app.exit()

    def submit_answer(self, status: str = "next") -> None:
        try:
            if not self.raw_options:
                val = self.query_one("#write-in-input", Input).value.strip()
                answer = val if val else "No response"
            else:
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

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("shift+tab", "backtab", "shift_tab"):
            event.prevent_default()
            event.stop()
            return


class ConfirmScreen(ModalScreen[str]):
    """Confirmation modal screen before submitting answers"""

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
            yield Markdown("### **Confirm your answers**\n\n" + self.summary, classes="modal-markdown")
            yield Label("enter: confirm • ←: back • esc: cancel", id="modal-hint")

    def action_confirm(self) -> None:
        self.dismiss("confirm")

    def action_go_back(self) -> None:
        self.dismiss("back")

    def action_cancel(self) -> None:
        self.dismiss("cancelled")

    def action_quit(self) -> None:
        self.app.exit()
