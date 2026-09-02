"""Modal hotkey hint widget with theme-colored keys and separators."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional, Union

from rich.console import RenderableType
from rich.table import Table
from textual.widgets import Label

from widgets.presentation.screens.constants import MODAL_HINT_ID
from widgets.presentation.widgets.footer_layout import format_hint

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
        return format_hint(self.actions_text())

    def format_close(self) -> str:
        """Format close hotkey with theme colors."""
        return format_hint(self.close_text())

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
    """Modal hotkey hint label rendering keys on the left and optional count/badge on the right."""

    DEFAULT_CSS = """
    ModalHint {
        width: 100%;
        height: auto;
        margin-top: 1;
        margin-bottom: 0;
        padding: 0;
    }
    """

    def __init__(
        self,
        text: Union[str, ModalHintConfig] = "",
        right_text: str = "",
        *,
        id: Optional[str] = MODAL_HINT_ID,
        classes: Optional[str] = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled)
        self.left_text = text
        self.right_text = right_text

    def render(self) -> RenderableType:
        if isinstance(self.left_text, ModalHintConfig):
            left_raw = self.left_text.to_hint_string()
        else:
            left_raw = str(self.left_text or "")
        left_formatted = format_hint(left_raw) if left_raw else ""

        if not self.right_text:
            return left_formatted

        table = Table.grid(expand=True)
        table.add_column(ratio=1, justify="left")
        table.add_column(justify="right")

        right_formatted = format_hint(self.right_text)
        table.add_row(left_formatted, right_formatted)
        return table

    def update(
        self,
        renderable: Union[RenderableType, ModalHintConfig] = "",
        right_text: str = "",
    ) -> Self:
        self.left_text = renderable
        self.right_text = right_text
        self.refresh()
        return self

