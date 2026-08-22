from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.base_selection import HeaderWrapOptionList
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    OPTIONS_LIST,
    OPTIONS_LIST_ID,
    SHIFT_TAB_KEYS,
    WRITE_IN_INPUT,
    WRITE_IN_INPUT_ID,
)


class WriteInInput(Input):
    """Custom Input widget that handles Up key to return focus to OptionList and prevents select-all"""

    def _clear_selection(self) -> None:
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

    def _on_focus(self, event: events.Focus) -> None:
        super()._on_focus(event)
        self._clear_selection()
        self.call_after_refresh(self._clear_selection)

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        cursor = self.cursor_position
        val_len = len(self.value)

        if key in ("up", "key_up"):
            if self.screen and getattr(self.screen, "raw_options", None):
                if hasattr(self.screen, "focus_options_list"):
                    getattr(self.screen, "focus_options_list")()
                    event.stop()
                    event.prevent_default()
                    return
            else:
                if self.screen and hasattr(self.screen, "action_go_back"):
                    getattr(self.screen, "action_go_back")()
                    event.stop()
                    event.prevent_default()
                    return

        elif key in ("down", "key_down"):
            if self.screen and getattr(self.screen, "raw_options", None):
                if hasattr(self.screen, "focus_first_option"):
                    getattr(self.screen, "focus_first_option")()
                    event.stop()
                    event.prevent_default()
                    return

        elif key in ("left", "key_left"):
            if cursor == 0:
                if self.screen and hasattr(self.screen, "action_go_back"):
                    getattr(self.screen, "action_go_back")()
                    event.stop()
                    event.prevent_default()
                    return

        elif key in ("right", "key_right"):
            if cursor == val_len:
                if self.screen and hasattr(self.screen, "action_go_next"):
                    getattr(self.screen, "action_go_next")()
                    event.stop()
                    event.prevent_default()
                    return

        await super()._on_key(event)


class ConfirmScreen(BaseModalScreen[str]):
    """Modal screen for requesting confirmation from the user (yes/no/cancel)"""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("left", "go_back", "Back"),
        ("enter", "confirm", "Confirm"),
    ]

    def __init__(self, summary: str):
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown("### **Confirmation Required**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield Markdown(self.summary, classes=MODAL_MARKDOWN)
            yield Label("enter: confirm • ←: back • esc: cancel", id=MODAL_HINT_ID)

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


class AskUserWizardScreen(BaseModalScreen[str]):
    """Unified modal screen that handles multi-question wizard without flickering."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("tab", "minimize", "Minimize"),
        ("left", "go_back", "Back"),
        ("right", "go_next", "Next"),
        ("enter", "go_next", "Next / Confirm"),
        ("space", "toggle_selection", "Toggle Selection"),
    ]

    def __init__(self, questions: list[dict], answers: dict | None = None, q_idx: int = 0):
        super().__init__()
        self.questions = questions or []
        self.answers = answers or {}
        self.q_idx = q_idx
        self.raw_options = []
        self.options = []

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="wizard-dialog"):
            yield Markdown("", id="wizard-title", classes=MODAL_MARKDOWN)
            yield HeaderWrapOptionList(id=OPTIONS_LIST_ID)
            yield WriteInInput(placeholder="Type response here and press Enter...", id=WRITE_IN_INPUT_ID)
            yield Label("", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        import time

        self._mount_time = time.time()
        self.update_step()
        self.call_after_refresh(self._force_modal_focus)
        self.set_timer(0.05, self._force_modal_focus)

    def _force_modal_focus(self) -> None:
        if not self.is_mounted:
            return
        if self.q_idx < len(self.questions):
            if self.raw_options:
                try:
                    self.query_one(OPTIONS_LIST, OptionList).focus()
                except Exception:
                    pass
            else:
                try:
                    self.query_one(WRITE_IN_INPUT, Input).focus()
                except Exception:
                    pass

    def update_step(self, target_highlight: int | None = None) -> None:
        title_md = self.query_one("#wizard-title", Markdown)
        opt_list = self.query_one(OPTIONS_LIST, OptionList)
        input_field = self.query_one(WRITE_IN_INPUT, Input)
        hint = self.query_one(MODAL_HINT, Label)

        if self.q_idx < len(self.questions):
            title_md.remove_class("confirm-summary")
            q = self.questions[self.q_idx]
            q_text = q.get("question", "")
            title_md.update(f"### **Question {self.q_idx + 1}/{len(self.questions)}**\n{q_text}")
            hint.update("enter: confirm • space: toggle • ←→: nav • tab: min • esc: cancel")

            self.raw_options = q.get("options") or []
            self.options = self.raw_options + ["Write-in..."] if self.raw_options else []
            prev_answer = self.answers.get(self.q_idx, {}).get("answer", "")

            if self.raw_options:
                opt_list.display = True
                opt_list.clear_options()

                if target_highlight is not None and target_highlight < len(self.options):
                    highlight_idx = target_highlight
                    if highlight_idx == len(self.options) - 1 and prev_answer and prev_answer not in self.raw_options:
                        input_field.value = prev_answer
                    elif highlight_idx < len(self.raw_options):
                        input_field.value = ""
                elif prev_answer:
                    if prev_answer in self.raw_options:
                        highlight_idx = self.raw_options.index(prev_answer)
                        input_field.value = ""
                    else:
                        highlight_idx = len(self.options) - 1
                        input_field.value = prev_answer
                        input_field.display = True
                else:
                    highlight_idx = 0
                    input_field.value = ""

                for idx, opt in enumerate(self.options):
                    is_selected = bool(
                        prev_answer
                        and (
                            (idx < len(self.raw_options) and prev_answer == self.raw_options[idx])
                            or (idx == len(self.options) - 1 and prev_answer not in self.raw_options)
                        )
                    )
                    tag = r"\[✓]" if is_selected else r"\[ ]"
                    opt_list.add_option(f"{tag} {opt}")

                opt_list.highlighted = highlight_idx
                if highlight_idx == len(self.options) - 1:
                    self.focus_write_in_input()
                else:
                    input_field.display = False
                    opt_list.focus()

            else:
                opt_list.display = False
                input_field.display = True
                input_field.value = prev_answer
                input_field.focus()
        else:
            blocks = []
            for idx, q in enumerate(self.questions):
                q_clean = q.get("question", "")
                ans_info = self.answers.get(idx, {})
                ans_val = ans_info.get("answer", "")
                ans_display = ans_val if ans_val else "(No response)"
                blocks.append(f"**{q_clean}**\n\n{ans_display}")

            summary = "\n\n&nbsp;\n\n".join(blocks)

            title_md.add_class("confirm-summary")
            title_md.update("### **Confirm Your Answers**\n\n" + summary)
            opt_list.display = False
            input_field.display = False
            hint.update("enter: confirm • ←: back • esc: cancel")
            self.focus()

    def focus_write_in_input(self) -> None:
        try:
            input_field = self.query_one(WRITE_IN_INPUT, Input)
            input_field.display = True
            input_field.focus()
        except Exception:
            pass

    def focus_options_list(self) -> None:
        if not self.raw_options:
            return
        try:
            input_field = self.query_one(WRITE_IN_INPUT, Input)
            opt_list = self.query_one(OPTIONS_LIST, OptionList)
            input_field.display = False
            opt_list.highlighted = max(0, len(self.options) - 2)
            opt_list.focus()
        except Exception:
            pass

    def focus_first_option(self) -> None:
        if not self.raw_options:
            return
        try:
            input_field = self.query_one(WRITE_IN_INPUT, Input)
            opt_list = self.query_one(OPTIONS_LIST, OptionList)
            input_field.display = False
            opt_list.highlighted = 0
            opt_list.focus()
        except Exception:
            pass


    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if not self.is_mounted or not self.raw_options or self.q_idx >= len(self.questions):
            return
        try:
            input_field = self.query_one(WRITE_IN_INPUT, Input)
            if event.option_index == len(self.options) - 1:
                self.focus_write_in_input()
            else:
                input_field.display = False
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not self.raw_options or self.q_idx >= len(self.questions):
            return
        import time

        if hasattr(self, "_mount_time") and (time.time() - self._mount_time < 0.25):
            return
        if event.option_index != len(self.options) - 1:
            self.submit_current_step()
        else:
            self.focus_write_in_input()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        import time

        if hasattr(self, "_mount_time") and (time.time() - self._mount_time < 0.25):
            return
        self.submit_current_step()

    def submit_current_step(self) -> None:
        if self.q_idx < len(self.questions):
            if not self.raw_options:
                val = self.query_one(WRITE_IN_INPUT, Input).value.strip()
                answer = val
            else:
                opt_list = self.query_one(OPTIONS_LIST, OptionList)
                idx = opt_list.highlighted
                if idx == len(self.options) - 1:
                    val = self.query_one(WRITE_IN_INPUT, Input).value.strip()
                    answer = val
                else:
                    answer = self.options[idx] if idx is not None and idx < len(self.options) else ""

            self.answers[self.q_idx] = {"answer": answer}
            self.q_idx += 1
            self.update_step()
        else:
            out_summary = ""
            for idx, q in enumerate(self.questions):
                q_clean = q.get("question", "")
                ans_info = self.answers.get(idx, {})
                ans_val = ans_info.get("answer", "")
                ans_display = ans_val if ans_val else "(No response)"
                out_summary += f"Question: {q_clean}\nAnswer: {ans_display}\n"
            self.dismiss(out_summary.strip())

    def action_toggle_selection(self) -> None:
        if not self.raw_options or self.q_idx >= len(self.questions):
            return
        try:
            opt_list = self.query_one(OPTIONS_LIST, OptionList)
            if not opt_list.has_focus:
                return
            idx = opt_list.highlighted
            if idx is not None and idx < len(self.raw_options):
                chosen = self.raw_options[idx]
                current_ans = self.answers.get(self.q_idx, {}).get("answer", "")
                if current_ans == chosen:
                    self.answers[self.q_idx] = {"answer": ""}
                else:
                    self.answers[self.q_idx] = {"answer": chosen}
                self.update_step(target_highlight=idx)
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss("Cancelled by user.")

    def action_minimize(self) -> None:
        self.dismiss({"action": "minimize", "answers": self.answers, "q_idx": self.q_idx})

    def action_go_back(self) -> None:
        if self.q_idx > 0:
            self.q_idx -= 1
            self.update_step()

    def action_go_next(self) -> None:
        """Right arrow: navigate to the next question; on the last one show/confirm summary."""
        if self.q_idx < len(self.questions):
            self.q_idx += 1
            self.update_step()
        else:
            self.submit_current_step()

    def action_quit(self) -> None:
        self.app.exit()

    def _on_key(self, event: events.Key) -> None:
        if event.key in SHIFT_TAB_KEYS:
            event.prevent_default()
            event.stop()
            return
