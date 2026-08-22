import os

from textual.containers import HorizontalScroll
from textual.widgets import Static

from core.domain.defaults.config import THEME_MUTED, THEME_SECONDARY


class AttachmentChip(Static):
    """Clickable chip representing a single attachment."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, attachment, *args, **kwargs) -> None:
        self.attachment = attachment
        fname = os.path.basename(attachment.path) if hasattr(attachment, "path") else str(attachment)
        if len(fname) > 24:
            fname = f"{fname[:10]}…{fname[-10:]}"
        text = (
            f"[{THEME_MUTED}]\\[img:\u00a0[/{THEME_MUTED}]"
            f"[{THEME_SECONDARY}]{fname}[/{THEME_SECONDARY}]"
            f"[{THEME_MUTED}]\u00a0×][/{THEME_MUTED}]"
        )
        super().__init__(text, *args, **kwargs)

    def on_click(self, event: object | None = None) -> None:
        """Clicking on a specific chip removes ONLY that attachment."""
        try:
            app = self.app
            if app:
                ci = app.query_one("#message-input")
                if hasattr(ci, "remove_clipboard_attachment"):
                    ci.remove_clipboard_attachment(self.attachment)
        except Exception:
            pass


class AttachmentBar(HorizontalScroll):
    """1-line horizontal scroll container for AttachmentChip widgets."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.attachments: list = []

    def update_attachments(self, attachments: list | None = None) -> None:
        if attachments is not None:
            self.attachments = list(attachments)
        try:
            self.remove_children()
        except Exception:
            pass

        if not self.attachments:
            self.styles.display = "none"
        else:
            self.styles.display = "block"
            for att in self.attachments:
                chip = AttachmentChip(att)
                try:
                    self.mount(chip)
                except Exception:
                    pass

        try:
            if self.app:
                ci = self.app.query_one("#message-input")
                if hasattr(ci, "update_height"):
                    ci.update_height()
        except Exception:
            pass
