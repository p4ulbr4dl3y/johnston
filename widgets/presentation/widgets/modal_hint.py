"""Modal hotkey hint widget with theme-colored keys and separators."""
from __future__ import annotations

import sys
from typing import Optional

from rich.console import RenderableType
from textual.widgets import Label

from widgets.presentation.screens.constants import MODAL_HINT_ID
from widgets.presentation.widgets.footer_layout import format_modal_hint

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

__all__ = ["ModalHint"]


class ModalHint(Label):
    """Modal hotkey hint label rendering keys in secondary theme color and separators in muted."""

    DEFAULT_CSS = """
    ModalHint {
        width: 100%;
        height: auto;
        text-align: left;
        margin-top: 1;
        margin-bottom: 0;
        padding: 0;
        text-wrap: wrap;
    }
    """

    def __init__(
        self,
        text: str = "",
        *,
        id: Optional[str] = MODAL_HINT_ID,
        classes: Optional[str] = None,
        disabled: bool = False,
    ) -> None:
        formatted = format_modal_hint(text) if text else ""
        super().__init__(formatted, id=id, classes=classes, disabled=disabled)

    def update(self, renderable: RenderableType = "") -> Self:
        if isinstance(renderable, str):
            renderable = format_modal_hint(renderable)
        return super().update(renderable)
