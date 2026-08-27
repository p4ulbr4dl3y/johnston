"""Theme domain entity and type definitions."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Theme:
    """Canonical theme specification for UI and syntax rendering."""

    name: str
    label: str
    dark: bool = True
    primary: str = "#ffffff"
    secondary: str = "#f4f4f5"
    muted: str = "#71717a"
    subtle: str = "#e4e4e7"
    tcss_vars: dict[str, str] = field(default_factory=dict)
    markdown_styles: dict[str, str] = field(default_factory=dict)
    syntax_tokens: dict[Any, str] = field(default_factory=dict)
