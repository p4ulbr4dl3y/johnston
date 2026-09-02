"""Modal dialog header widget displaying title on the left and exit hotkey on the right."""
from __future__ import annotations

import re
from typing import Optional

from rich.console import RenderableType
from rich.markup import escape
from rich.table import Table
from textual.widgets import Static

from widgets.presentation.widgets.footer_layout import format_hint, get_theme_colors

__all__ = ["ModalHeader"]


class ModalHeader(Static):
    """Header widget for modal dialogs displaying title on the left and esc hint on the right."""

    DEFAULT_CSS = """
    ModalHeader {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
    }
    """

    def __init__(
        self,
        title: str = "",
        esc_hint: str = "esc: close",
        *,
        id: Optional[str] = None,
        classes: Optional[str] = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled)
        self.title_text = title
        self.esc_hint = esc_hint

    def render(self) -> RenderableType:
        table = Table.grid(expand=True)
        table.add_column(ratio=1, justify="left")
        table.add_column(justify="right")

        t_primary, _, _, _ = get_theme_colors()
        clean_title = re.sub(r"^[#\s*]+|[#\s*]+$", "", self.title_text).strip()
        left_text = f"[bold {t_primary}]{escape(clean_title)}[/]"
        right_text = format_hint(self.esc_hint) if self.esc_hint else ""
        table.add_row(left_text, right_text)
        return table
