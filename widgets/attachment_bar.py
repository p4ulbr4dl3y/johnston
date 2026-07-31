import time
from typing import List

from textual.widgets import Static


class ClipboardAttachment:
    """Represents a clipboard image attachment"""

    def __init__(self, path: str, width: int = 0, height: int = 0, size_kb: float = 0.0):
        self.path = path
        self.width = width
        self.height = height
        self.size_kb = size_kb
        self.id = f"att_{int(time.time() * 1000)}"

    @property
    def chip_label(self) -> str:
        if self.width and self.height:
            return f"[bold #ffffff]📎 [Clipboard Image ({self.width}x{self.height}) [dim #a1a1aa]✕[/dim #a1a1aa]][/bold #ffffff]"
        return "[bold #ffffff]📎 [Clipboard Image [dim #a1a1aa]✕[/dim #a1a1aa]][/bold #ffffff]"


class AttachmentBar(Static):
    """Displays chips for attached clipboard images above chat input"""

    DEFAULT_CSS = """
    AttachmentBar {
        display: none;
        height: 1;
        background: #18181b;
        color: #a1a1aa;
        padding: 0 1;
        content-align: left middle;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.attachments: List[ClipboardAttachment] = []

    def update_attachments(self, attachments: List[ClipboardAttachment]) -> None:
        self.attachments = list(attachments)
        if not self.attachments:
            self.update("")
            self.display = False
        else:
            labels = [att.chip_label for att in self.attachments]
            self.update("  ".join(labels))
            self.display = True

    def on_click(self) -> None:
        """Clear attachments when clicked"""
        if self.attachments:
            if self.app:
                from widgets.chat_input import ChatInput
                try:
                    chat_input = self.app.query_one("#message-input", ChatInput)
                    chat_input.clear_clipboard_attachments()
                except Exception:
                    pass
