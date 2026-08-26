from widgets.presentation.screens.base_selection import BaseSelectionScreen


class SessionConflictScreen(BaseSelectionScreen[str]):
    """Modal dialog shown when attempting to open a session active in another terminal."""

    def __init__(self, session_id: str, session_title: str = ""):
        self.session_id = session_id
        items = ["fork", "steal", "readonly"]
        options = [
            "Fork session (copy & continue)",
            "Steal session (take over)",
            "Open read-only",
        ]
        title = "### **Session Busy**\n\nSession is open in another terminal"
        super().__init__(
            title=title,
            options=options,
            items=items,
            default_value="fork",
            show_search=False,
            hint_text="enter: select • ↑↓: nav • esc: back",
            dialog_classes="modal-dialog-medium",
        )
