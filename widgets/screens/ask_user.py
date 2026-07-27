from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown, OptionList


class WriteInInput(Input):
    """Custom Input widget that handles Up key to return focus to OptionList"""

    def _on_focus(self, event: events.Focus) -> None:
        super()._on_focus(event)
        val_len = len(self.value)
        self.cursor_position = val_len
        try:
            from textual.widgets._input import Selection
            self.selection = Selection(val_len, val_len)
        except Exception:
            try:
                self.selection = (val_len, val_len)
            except Exception:
                pass

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("up", "key_up"):
            if self.screen and hasattr(self.screen, "focus_options_list"):
                getattr(self.screen, "focus_options_list")()
                event.stop()
                event.prevent_default()
                return
        super()._on_key(event)


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
            yield WriteInInput(placeholder="Type response here and press Enter...", id="write-in-input")
            yield Label("enter: select • ←: back • →: next • esc: cancel", id="modal-hint")

    def focus_write_in_input(self) -> None:
        try:
            input_field = self.query_one("#write-in-input", Input)
            input_field.display = True
            input_field.focus()
            val_len = len(input_field.value)
            input_field.cursor_position = val_len
            try:
                from textual.widgets._input import Selection
                input_field.selection = Selection(val_len, val_len)
            except Exception:
                try:
                    input_field.selection = (val_len, val_len)
                except Exception:
                    pass
        except Exception:
            pass

    def focus_options_list(self) -> None:
        if not self.raw_options:
            return
        try:
            input_field = self.query_one("#write-in-input", Input)
            opt_list = self.query_one("#options-list", OptionList)
            input_field.display = False
            opt_list.highlighted = max(0, len(self.options) - 2)
            opt_list.focus()
        except Exception:
            pass

    def on_mount(self) -> None:
        import time
        self._mount_time = time.time()
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
            self.focus_write_in_input()
        else:
            opt_list.focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if not self.is_mounted or not self.raw_options:
            return
        try:
            input_field = self.query_one("#write-in-input", Input)
            if event.option_index == len(self.options) - 1:
                self.focus_write_in_input()
            else:
                input_field.display = False
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not self.raw_options:
            return
        import time
        if hasattr(self, "_mount_time") and (time.time() - self._mount_time < 0.25):
            return
        try:
            if event.option_index != len(self.options) - 1:
                self.submit_answer()
            else:
                self.focus_write_in_input()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        import time
        if hasattr(self, "_mount_time") and (time.time() - self._mount_time < 0.25):
            return
        self.submit_answer()

    def on_key(self, event: events.Key) -> None:
        if event.key in ("up", "key_up") and self.raw_options:
            self.focus_options_list()
            event.stop()
            event.prevent_default()

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
    """Modal screen for requesting confirmation from the user (yes/no/cancel)"""

    ALLOW_SELECT = False
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

    def on_mount(self) -> None:
        import time
        self._mount_time = time.time()

    def action_confirm(self) -> None:
        import time
        if hasattr(self, "_mount_time") and (time.time() - self._mount_time < 0.25):
            return
        self.dismiss("confirm")

    def action_go_back(self) -> None:
        self.dismiss("back")

    def action_cancel(self) -> None:
        self.dismiss("cancelled")

    def action_quit(self) -> None:
        self.app.exit()
