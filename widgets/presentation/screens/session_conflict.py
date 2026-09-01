from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.constants import ESC_HINT_BACK
from widgets.utils.responsive import MODAL_COMPACT_MAX_WIDTH, MODAL_MIN_WIDTH


class SessionConflictScreen(BaseSelectionScreen[str]):
    """Modal dialog shown when attempting to open a session active in another terminal."""

    def __init__(
        self,
        session_id: str,
        session_title: str = "",
        min_dialog_width: int = MODAL_MIN_WIDTH,
        dialog_classes: str = "modal-dialog-compact",
    ):
        self.session_id = session_id
        self.session_title = session_title
        items = ["readonly", "steal"]
        options = [
            "Open read-only [dim](fork on edit)[/]",
            "Steal session [dim](take over)[/]",
        ]
        title = "### **Session is Open in Another Terminal**"
        super().__init__(
            title=title,
            options=options,
            items=items,
            default_value="readonly",
            show_search=False,
            hint_text=f"enter: select • {ESC_HINT_BACK}",
            dialog_classes=dialog_classes,
            fit_content=True,
            min_dialog_width=min_dialog_width,
            max_dialog_width=MODAL_COMPACT_MAX_WIDTH,
        )
