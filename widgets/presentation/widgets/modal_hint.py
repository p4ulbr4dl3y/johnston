"""Modal hotkey hint widget with theme-colored keys and separators."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional, Union

from rich.console import RenderableType
from textual.widgets import Label

from widgets.presentation.screens.constants import MODAL_HINT_ID
from widgets.presentation.widgets.footer_layout import format_modal_hint

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

__all__ = ["ModalHint", "ModalHintConfig"]


@dataclass(frozen=True)
class ModalHintConfig:
    """Typed modal hint configuration for consistent key hints and esc actions."""

    actions: list[Union[tuple[str, str], str]] = field(default_factory=list)
    close_key: str = "esc"
    close_label: str = "close"

    def actions_text(self) -> str:
        parts: list[str] = []
        for item in self.actions:
            if isinstance(item, tuple) and len(item) == 2:
                k, v = item
                parts.append(f"{k}: {v}" if v else k)
            elif isinstance(item, str) and item:
                parts.append(item)
        return " • ".join(parts)

    def close_text(self) -> str:
        if not self.close_key:
            return ""
        return f"{self.close_key}: {self.close_label}" if self.close_label else self.close_key

    def format_actions(self) -> str:
        """Format action hotkeys with theme colors."""
        return format_modal_hint(self.actions_text())

    def format_close(self) -> str:
        """Format close hotkey with theme colors."""
        return format_modal_hint(self.close_text())

    def to_hint_string(self) -> str:
        """Format full combined hotkey hint string."""
        parts: list[str] = []
        act = self.actions_text()
        if act:
            parts.append(act)
        close = self.close_text()
        if close:
            parts.append(close)
        return " • ".join(parts)


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
        text: Union[str, ModalHintConfig] = "",
        *,
        id: Optional[str] = MODAL_HINT_ID,
        classes: Optional[str] = None,
        disabled: bool = False,
    ) -> None:
        if isinstance(text, ModalHintConfig):
            raw_str = text.to_hint_string()
        else:
            raw_str = text or ""
        formatted = format_modal_hint(raw_str) if raw_str else ""
        super().__init__(formatted, id=id, classes=classes, disabled=disabled)

    def update(self, renderable: Union[RenderableType, ModalHintConfig] = "") -> Self:
        if isinstance(renderable, ModalHintConfig):
            renderable = format_modal_hint(renderable.to_hint_string())
        elif isinstance(renderable, str):
            renderable = format_modal_hint(renderable)
        return super().update(renderable)

