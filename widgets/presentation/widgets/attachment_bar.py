from textual.containers import HorizontalScroll
from textual.widgets import Static


class AttachmentChip(Static):
    """Clickable chip representing a single attachment."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, attachment, index: int = 1, *args, **kwargs) -> None:
        self.attachment = attachment
        self.index = index
        try:
            from widgets.app.theme_manager import theme_manager
            t = theme_manager.current_theme
            muted, secondary = t.muted, t.secondary
        except Exception:
            from core.domain.defaults.config import THEME_MUTED, THEME_SECONDARY
            muted, secondary = THEME_MUTED, THEME_SECONDARY
        text = (
            f"[{muted}]\\[[/{muted}]"
            f"[{secondary}]Image #{index}[/{secondary}]"
            f"[{muted}]\u00a0×][/{muted}]"
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


class AttachmentHint(Static):
    """Hint label showing hotkey for detaching last attachment."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, **kwargs) -> None:
        from widgets.presentation.widgets.footer_layout import format_modal_hint, get_theme_colors

        _, _, t_muted, _ = get_theme_colors()
        hint = format_modal_hint("ctrl+d: detach")
        text = f"[{t_muted}]•[/] {hint}"
        super().__init__(text, *args, **kwargs)



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
            for idx, att in enumerate(self.attachments, start=1):
                chip = AttachmentChip(att, index=idx)
                try:
                    self.mount(chip)
                except Exception:
                    pass
            try:
                hint = AttachmentHint()
                self.mount(hint)
            except Exception:
                pass

        try:
            if self.app:
                ci = self.app.query_one("#message-input")
                if hasattr(ci, "update_height"):
                    ci.update_height()
        except Exception:
            pass

