"""Theme domain entity and type definitions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pygments.token import Token


def _resolve_style_vars(style_str: str, var_map: dict[str, str]) -> str:
    """Replace $var or $var-name references with their mapped hex values."""
    if not isinstance(style_str, str) or "$" not in style_str:
        return style_str

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return var_map.get(var_name, match.group(0))

    return re.sub(r"\$([a-zA-Z0-9_-]+)", replacer, style_str)


def _parse_token(tok_key: Any) -> Any:
    """Resolve string or Token representation to Pygments Token."""
    if isinstance(tok_key, str):
        parts = tok_key.strip().split(".")
        if parts and parts[0] == "Token":
            parts = parts[1:]
        current = Token
        for p in parts:
            if hasattr(current, p):
                current = getattr(current, p)
            else:
                return Token
        return current
    return tok_key


def _is_ansi(bg_app: str, name: str) -> bool:
    """Return True when the theme uses ANSI/native terminal colors."""
    return bg_app in ("ansi_default", "transparent") or name == "native"


def is_ansi_theme(theme: Theme) -> bool:
    """Return True if the theme is an ANSI/native theme (uses terminal colors)."""
    bg_app = theme.tcss_vars.get("bg-app", "#09090b")
    return _is_ansi(bg_app, theme.name)


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

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("Theme name must be a non-empty string")
        if not self.label or not isinstance(self.label, str):
            raise ValueError("Theme label must be a non-empty string")

    @property
    def accent_info(self) -> str:
        """Accent color for info/active state (blue)."""
        return self.tcss_vars.get("accent-info", "#61afef" if self.dark else "#0969da")

    @property
    def accent_warning(self) -> str:
        """Accent color for warning/running state (yellow/orange)."""
        return self.tcss_vars.get("accent-warning", "#d4a259" if self.dark else "#9a6700")

    @property
    def accent_error(self) -> str:
        """Accent color for error/failed state (red)."""
        return self.tcss_vars.get("accent-error", "#d15858" if self.dark else "#cf222e")

    @property
    def accent_success(self) -> str:
        """Accent color for success/completed state (green)."""
        return self.tcss_vars.get("accent-success", "#5ea876" if self.dark else "#1a7f37")

    def to_dict(self) -> dict[str, Any]:
        """Serialize Theme to a JSON-serializable dictionary."""
        syntax = {str(k): str(v) for k, v in self.syntax_tokens.items()}
        return {
            "name": self.name,
            "label": self.label,
            "dark": self.dark,
            "primary": self.primary,
            "secondary": self.secondary,
            "muted": self.muted,
            "subtle": self.subtle,
            "tcss_vars": dict(self.tcss_vars),
            "markdown_styles": dict(self.markdown_styles),
            "syntax_tokens": syntax,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Theme:
        """Create and validate Theme from a dictionary."""
        if not isinstance(data, dict):
            raise ValueError("Theme data must be a dictionary")
        name = data.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            raise ValueError("Theme 'name' is required and must be a non-empty string")
        name = name.strip()
        label = str(data.get("label", name.replace("-", " ").title()))
        dark = bool(data.get("dark", True))
        primary = str(data.get("primary", "#ffffff"))
        secondary = str(data.get("secondary", "#f4f4f5"))
        muted = str(data.get("muted", "#71717a"))
        subtle = str(data.get("subtle", "#e4e4e7"))

        tcss_vars = {str(k): str(v) for k, v in data.get("tcss_vars", {}).items()}
        for palette_key, palette_val in (
            ("primary", primary),
            ("secondary", secondary),
            ("muted", muted),
            ("subtle", subtle),
        ):
            if palette_key not in tcss_vars:
                tcss_vars[palette_key] = palette_val
        if "bg-overlay" not in tcss_vars:
            bg_app = tcss_vars.get("bg-app", "#09090b")
            tcss_vars["bg-overlay"] = "transparent" if _is_ansi(bg_app, name) else "#000000 45%"

        var_map: dict[str, str] = {
            "primary": primary,
            "secondary": secondary,
            "muted": muted,
            "subtle": subtle,
        }
        for k, v in tcss_vars.items():
            var_map[k] = str(v)
            var_map[k.replace("-", "_")] = str(v)

        markdown_styles = {
            str(k): _resolve_style_vars(str(v), var_map)
            for k, v in data.get("markdown_styles", {}).items()
        }

        raw_syntax = data.get("syntax_tokens", {})
        syntax_tokens = {}
        if isinstance(raw_syntax, dict):
            for k, v in raw_syntax.items():
                syntax_tokens[_parse_token(k)] = _resolve_style_vars(str(v), var_map)

        return cls(
            name=name,
            label=label,
            dark=dark,
            primary=primary,
            secondary=secondary,
            muted=muted,
            subtle=subtle,
            tcss_vars=tcss_vars,
            markdown_styles=markdown_styles,
            syntax_tokens=syntax_tokens,
        )

