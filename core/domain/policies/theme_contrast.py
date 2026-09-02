"""WCAG contrast policy for theme tokens.

Terminal UIs have no accessibility tree to lean on, so colour contrast is the
one part of WCAG 2.1 that transfers directly: 1.4.3 (4.5:1 for body text,
3:1 for large text) and 1.4.11 (3:1 for boundaries of UI components).

The helpers here are the single source of truth for those thresholds and are
used by:

- the theme token test suite (``tests/test_ui_theme_contrast.py``),
- the native/ANSI adaptive palette (``core/infrastructure/platform/terminal_theme.py``),
- tooling that regenerates ``core/domain/defaults/themes.json``.
"""

from __future__ import annotations

# WCAG 2.1 AA
TEXT_CONTRAST_AA = 4.5
TEXT_CONTRAST_AA_LARGE = 3.0
UI_CONTRAST_AA = 3.0

_HEX_LEN = 6


def _channel(value: float) -> float:
    value = value / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """Relative luminance (0..1) of a ``#rrggbb`` / ``#rgb`` colour."""
    if not isinstance(color, str):
        return 0.0
    raw = color.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) < _HEX_LEN:
        return 0.0
    try:
        r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return 0.0
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two hex colours (1.0 .. 21.0)."""
    a, b = relative_luminance(foreground), relative_luminance(background)
    low, high = sorted((a, b))
    return (high + 0.05) / (low + 0.05)


def meets_contrast(foreground: str, background: str, target: float = TEXT_CONTRAST_AA) -> bool:
    """True when ``foreground`` on ``background`` reaches ``target``."""
    return contrast_ratio(foreground, background) >= target


def parse_css_color(value: str) -> tuple[int, int, int, float] | None:
    """Parse ``#rrggbb`` or ``rgba(r,g,b,a)`` into ``(r, g, b, alpha)``.

    Returns ``None`` for the placeholders the terminal resolves at runtime
    (``ansi_default``, ``transparent``) — their effective colour is unknown.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.startswith("#"):
        digits = raw[1:]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) < _HEX_LEN:
            return None
        try:
            r, g, b = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
        return r, g, b, 1.0
    if raw.startswith("rgba(") or raw.startswith("rgb("):
        parts = raw[raw.index("(") + 1 : raw.rindex(")")].split(",")
        try:
            numbers = [float(p.strip().rstrip("%")) for p in parts]
        except ValueError:
            return None
        alpha = numbers[3] if len(numbers) > 3 else 1.0
        return int(numbers[0]), int(numbers[1]), int(numbers[2]), alpha
    return None


def composite(foreground: str, background: str) -> str | None:
    """Flatten a translucent colour over an opaque one (``#rrggbb`` result).

    Used to evaluate the *effective* colour of content shown behind a modal
    scrim: the scrim (``bg-overlay``) is painted over the app background, so
    anything that has to stay visible next to it must be measured against the
    composite, not against the raw token.
    """
    top, bottom = parse_css_color(foreground), parse_css_color(background)
    if top is None or bottom is None:
        return None
    tr, tg, tb, alpha = top
    br, bg, bb, _ = bottom
    mixed = [round(tr * alpha + ch * (1 - alpha)) for ch, tr in ((br, tr), (bg, tg), (bb, tb))]
    return "#%02x%02x%02x" % tuple(max(0, min(255, v)) for v in mixed)


def meets_on_all(foreground: str, backgrounds: list[str], target: float = TEXT_CONTRAST_AA) -> bool:
    """True when ``foreground`` reaches ``target`` on every opaque background given.

    Non-hex placeholders (``ansi_default``, ``transparent``, ``rgba(...)``) are
    skipped: their effective colour is unknown until the terminal reports it.
    """
    opaque = [bg for bg in backgrounds if isinstance(bg, str) and bg.startswith("#")]
    if not opaque:
        return True
    return all(meets_contrast(foreground, bg, target) for bg in opaque)
