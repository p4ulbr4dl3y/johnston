from widgets.presentation.screens.base_selection import BaseSelectionScreen


class SessionConflictScreen(BaseSelectionScreen[str]):
    """Modal dialog shown when attempting to open a session active in another terminal."""

    def __init__(self, session_id: str, session_title: str = ""):
        self.session_id = session_id
        items = ["readonly", "steal"]
        options = [
            "Open read-only [dim #71717a](fork on edit)[/]",
            "Steal session [dim #71717a](take over)[/]",
        ]
        super().__init__(
            title="### **Session is Open in Another Terminal**",
            options=options,
            items=items,
            default_value="readonly",
            show_search=False,
            hint_text="enter: select • ↑↓: nav • esc: back",
            fit_content=True,
        )
