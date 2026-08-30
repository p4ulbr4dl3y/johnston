from typing import Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, OptionList, Static

from core.application.session.actions import RewindEntry
from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.base_selection import HeaderWrapOptionList
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    MODAL_OPTION_LIST_ID,
    TAB_KEYS,
)
from widgets.presentation.screens.rewind import RewindSelection, format_rewind_files
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.responsive import (
    MODAL_MEDIUM_MAX_WIDTH,
    MODAL_MIN_WIDTH,
    apply_modal_fit,
)
from widgets.utils.row_format import MODAL_DEFAULT_ROW_WIDTH, ellipsize, option_list_row_width


class RewindActionScreen(BaseModalScreen[Optional[RewindSelection]]):
    """Modal dialog for selecting rollback action (conversation vs code vs diff)."""

    def __init__(
        self,
        entry: RewindEntry,
        session_id: Optional[str] = None,
        project_path: Optional[str] = None,
        user_messages: Optional[list[RewindEntry]] = None,
    ):
        super().__init__()
        self.entry = entry
        self.session_id = session_id
        self.project_path = project_path
        self.user_messages = user_messages or []
        self.items = ["conversation", "both", "diff"]
        self.options = [
            "Conversation only [dim](keep current code)[/]",
            "Both [dim](restore code & conversation)[/]",
            "View diff [dim](inspect changes)[/]",
        ]

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-medium"):
            yield Markdown("### **Rollback Action**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield Static("", id="rewind-files", classes=MODAL_MARKDOWN, markup=False)
            yield HeaderWrapOptionList(*self.options, id=MODAL_OPTION_LIST_ID)
            yield ModalHint("enter: select • ↑↓: nav • esc: back", id=MODAL_HINT_ID)

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(f"#{MODAL_OPTION_LIST_ID}", OptionList)
        except Exception:
            opt_list = None
        return option_list_row_width(opt_list, MODAL_DEFAULT_ROW_WIDTH)

    def _apply_dialog_fit(self) -> None:
        try:
            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
            apply_modal_fit(
                dialog,
                64,
                min_width=MODAL_MIN_WIDTH,
                max_width=MODAL_MEDIUM_MAX_WIDTH,
            )
        except Exception:
            pass

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_dialog_fit()
        self._update_files_display()
        try:
            opt_list = self.query_one(f"#{MODAL_OPTION_LIST_ID}", OptionList)
            opt_list.highlighted = 0
            opt_list.focus()
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()
        self._update_files_display()

    def _update_files_display(self) -> None:
        try:
            files_widget = self.query_one("#rewind-files", Static)
            if self.entry.changed_files:
                target_w = self._row_width()
                files_widget.update(
                    format_rewind_files(
                        self.entry.changed_files,
                        self.entry.git_stats,
                        max_width=target_w,
                    )
                )
                files_widget.display = True
            else:
                files_widget.display = False
        except Exception:
            pass

    def _open_diff_viewer(self) -> None:
        from core.domain.ports.checkpoint import get_checkpoint_manager
        from widgets.presentation.screens.diff import DiffScreen

        seq_idx = 0
        for i, m in enumerate(self.user_messages):
            if m.index == self.entry.index:
                seq_idx = i
                break

        diff_items = []
        if self.session_id:
            try:
                cm = get_checkpoint_manager()
                if cm:
                    diff_items = cm.get_checkpoint_diff(
                        self.session_id,
                        seq_idx,
                        project_path=self.project_path,
                        scoped_files=self.entry.changed_files if self.entry.changed_files else None,
                    )
            except Exception:
                diff_items = []

        clean = " ".join(self.entry.text.replace("\n", " ").replace("\r", " ").split())
        clean_preview = ellipsize(clean, 60) if clean else "(empty message)"

        app = getattr(self, "app", None)
        if app:
            app.push_screen(DiffScreen(diff_items, title=f"Rollback: {clean_preview}", from_rewind=True))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx < 0 or idx >= len(self.items):
            event.stop()
            return

        action = self.items[idx]
        if action == "both":
            self.dismiss(RewindSelection(index=self.entry.index, restore_code=True))
        elif action == "conversation":
            self.dismiss(RewindSelection(index=self.entry.index, restore_code=False))
        elif action == "diff":
            self._open_diff_viewer()
        event.stop()

    def _on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.prevent_default()
            event.stop()
            return
        if event.key in TAB_KEYS:
            event.prevent_default()
            event.stop()
            return

    def action_cancel(self) -> None:
        self.dismiss(None)
