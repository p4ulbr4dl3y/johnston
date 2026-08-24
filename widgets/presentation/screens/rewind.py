from dataclasses import dataclass
from typing import Any, Optional

from rich.markup import escape
from textual.widgets import Input, Label, Markdown, OptionList

from core.application.session.actions import RewindEntry
from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.constants import (
    MODAL_HINT,
    MODAL_MARKDOWN,
    MODAL_OPTION_LIST,
)


@dataclass
class RewindSelection:
    index: int
    restore_code: bool = True


class RewindScreen(BaseSelectionScreen[Any]):
    """Modal rollback screen (/rewind) with 2-step selection for code vs conversation."""

    def __init__(
        self,
        user_messages: list[RewindEntry],
        checkpoints_enabled: bool = True,
    ):
        self.user_messages = user_messages
        self.checkpoints_enabled = checkpoints_enabled
        self.step = 1
        self.selected_entry: Optional[RewindEntry] = None

        options = []
        for msg in user_messages:
            text = msg.text
            diff_stat = msg.git_stats

            clean = " ".join(text.replace("\n", " ").replace("\r", " ").split())
            if len(clean) > 55:
                clean = clean[:55] + "..."
            opt_text = clean or "(empty message)"
            escaped_text = escape(opt_text)

            if checkpoints_enabled:
                stat_label = diff_stat or "no checkpoint"
                opt = f"{escaped_text} [dim]{escape(f'[{stat_label}]')}[/dim]"
            else:
                opt = escaped_text
            options.append(opt)

        title = "### **Select Message to Rollback To**"

        items = [m.index for m in user_messages]
        default_val = items[-1] if items else -1
        super().__init__(
            title=title,
            options=options,
            items=items,
            default_value=default_val,
            dialog_classes="modal-dialog-medium",
        )

    def _show_step_2(self, entry: RewindEntry) -> None:
        self.step = 2
        self.selected_entry = entry

        clean = " ".join(entry.text.replace("\n", " ").replace("\r", " ").split())
        if len(clean) > 40:
            clean = clean[:40] + "..."
        escaped_preview = escape(clean or "(empty message)")
        stat_info = f" [dim]({escape(entry.git_stats)})[/dim]" if entry.git_stats else ""

        title = f"### **Rollback: {escaped_preview}{stat_info}**"
        try:
            md = self.query_one(f".{MODAL_MARKDOWN}", Markdown)
            md.update(title)
        except Exception:
            pass

        step2_options = [
            "Rollback conversation & files [dim](revert code)[/dim]",
            "Rollback conversation only [dim](keep current code)[/dim]",
            "Cancel",
        ]
        step2_actions = ["both", "conversation", "cancel"]

        self.filtered_options = step2_options
        self.filtered_items = step2_actions

        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
            opt_list.clear_options()
            opt_list.add_options(step2_options)
            opt_list.highlighted = 0
            opt_list.focus()
        except Exception:
            pass

        try:
            hint = self.query_one(MODAL_HINT, Label)
            hint.update("enter: select • ↑↓: nav • esc: back to messages")
        except Exception:
            pass

    def _show_step_1(self) -> None:
        self.step = 1
        self.selected_entry = None

        try:
            md = self.query_one(f".{MODAL_MARKDOWN}", Markdown)
            md.update(self.title)
        except Exception:
            pass

        self.filtered_options = list(self.raw_options)
        self.filtered_items = list(self.raw_items)

        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
            opt_list.clear_options()
            opt_list.add_options(self.filtered_options)
            default_idx = None
            if self.default_value is not None and self.default_value in self.raw_items:
                try:
                    default_idx = self.raw_items.index(self.default_value)
                except Exception:
                    pass
            opt_list.highlighted = default_idx
            opt_list.focus()
        except Exception:
            pass

        try:
            hint = self.query_one(MODAL_HINT, Label)
            hint.update(self.hint_text)
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx < 0 or idx >= len(self.filtered_items):
            event.stop()
            return

        if self.step == 1:
            if 0 <= idx < len(self.user_messages):
                selected_entry = self.user_messages[idx]
                if not self.checkpoints_enabled:
                    self.dismiss(RewindSelection(index=selected_entry.index, restore_code=False))
                    return
                self._show_step_2(selected_entry)
            event.stop()
            return
        elif self.step == 2:
            action = self.filtered_items[idx]
            if action == "both" and self.selected_entry is not None:
                self.dismiss(RewindSelection(index=self.selected_entry.index, restore_code=True))
            elif action == "conversation" and self.selected_entry is not None:
                self.dismiss(RewindSelection(index=self.selected_entry.index, restore_code=False))
            elif action == "cancel":
                self.dismiss(None)
            event.stop()
            return

    def on_input_submitted(self, event: Input.Submitted) -> None:
        opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
        idx = opt_list.highlighted
        if idx is not None:
            self.on_option_list_option_selected(OptionList.OptionSelected(opt_list, idx, None))

    def action_cancel(self) -> None:
        if self.step == 2:
            self._show_step_1()
        else:
            self.dismiss(None)
