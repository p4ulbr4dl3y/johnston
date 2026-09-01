"""Runtime access to the active theme's semantic colours.

Tool cards paint a status dot *and* the tool name next to it with one accent
colour. Those colours used to be module constants tuned for a single dark
theme, so they landed at 2.3–2.9:1 on light surfaces and the other 20 themes
had no say in them at all.

Colours now come from the active theme's ``accent-*`` tokens and are nudged
(toward white on dark surfaces, toward black on light ones) until they clear
WCAG AA on the surface they are painted on, so a theme can be as expressive as
it likes without producing unreadable status text.
"""

from __future__ import annotations

from core.domain.defaults.config import (
    COLOR_STATUS_ERROR,
    COLOR_STATUS_RUNNING,
    COLOR_STATUS_SUCCESS,
)
from core.domain.policies.theme_contrast import TEXT_CONTRAST_AA, contrast_ratio

# state -> (theme token, pre-audit constant used as fallback)
STATUS_TOKENS: dict[str, tuple[str, str]] = {
    "running": ("accent-warning", COLOR_STATUS_RUNNING),
    "error": ("accent-error", COLOR_STATUS_ERROR),
    "success": ("accent-success", COLOR_STATUS_SUCCESS),
}

FALLBACK_SURFACE = "#18181b"


def _hex2rgb(color: str) -> list[int]:
    raw = color.lstrip("#")
    return [int(raw[i : i + 2], 16) for i in (0, 2, 4)]


def _mix(color: str, target: str, t: float) -> str:
    a, b = _hex2rgb(color), _hex2rgb(target)
    return "#%02x%02x%02x" % tuple(
        max(0, min(255, int(round(a[i] * (1 - t) + b[i] * t)))) for i in range(3)
    )


def _raise_to(color: str, backgrounds: list[str], target: float) -> str:
    """Smallest nudge (either direction) that reaches ``target`` on every background.

    A status dot is painted on the app background but the same widget is reused
    inside the task console, whose panels sit on ``bg-surface``; both are
    checked so a theme accent cannot be legible in one place and not the other.
    """
    for step in range(0, 101):
        for end in ("#ffffff", "#000000"):
            candidate = _mix(color, end, step / 100)
            if all(contrast_ratio(candidate, bg) >= target for bg in backgrounds):
                return candidate
    return color


def active_theme_vars() -> dict[str, str]:
    """``tcss_vars`` of the theme currently in effect (adapted for native/ANSI)."""
    try:
        from widgets.app.theme_manager import theme_manager

        return dict(theme_manager.current_theme.tcss_vars)
    except Exception:
        return {}


def status_color(state: str, background: str | None = None) -> str:
    """Contrast-safe colour for a tool status dot and its label."""
    token, fallback = STATUS_TOKENS.get(state, STATUS_TOKENS["success"])
    variables = active_theme_vars()
    color = variables.get(token) or fallback
    if not isinstance(color, str) or not color.startswith("#"):
        return fallback

    given = [background] if background else [variables.get("bg-app"), variables.get("bg-surface")]
    backgrounds = [bg for bg in given if isinstance(bg, str) and bg.startswith("#")] or [FALLBACK_SURFACE]
    if all(contrast_ratio(color, bg) >= TEXT_CONTRAST_AA for bg in backgrounds):
        return color
    return _raise_to(color, backgrounds, TEXT_CONTRAST_AA)
