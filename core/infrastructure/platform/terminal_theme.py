"""Adaptive terminal palette and OKLab perceptual color math matching Cline."""

from __future__ import annotations

import math
import os
import re
import sys
import time
from typing import Any, Optional, Tuple

BASE_LIFT = 0.09
LIFT_DAMPING = 3.0
CHROMA_NUDGE = 0.003
LIGHT_THEME_THRESHOLD = 0.5
RULE_BASE_LIFT = 0.20

_HEX6_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_CACHED_TERMINAL_COLORS: Optional[Tuple[Optional[str], Optional[str]]] = None


def normalize_hex(color: str | None) -> str | None:
    """Normalize 3-hex or 6-hex strings to standard #rrggbb lowercase."""
    if not color:
        return None
    color = color.strip()
    if _HEX6_RE.match(color):
        return color.lower()
    if re.match(r"^#[0-9a-fA-F]{3}$", color):
        return f"#{color[1]}{color[1]}{color[2]}{color[2]}{color[3]}{color[3]}".lower()
    return None


def srgb_to_linear(c: float) -> float:
    """Convert sRGB channel value [0, 1] to linear gamma."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    """Convert linear gamma channel value to sRGB [0, 1]."""
    v = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055
    return max(0.0, min(1.0, v))


def _cbrt(x: float) -> float:
    """Cube root helper compatible with Python 3.10+."""
    if hasattr(math, "cbrt"):
        return math.cbrt(x)
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


def hex_to_oklab(hex_str: str) -> tuple[float, float, float]:
    """Convert a hex color string to OKLab (L, a, b) space."""
    clean_hex = (normalize_hex(hex_str) or "#000000").lstrip("#")
    r = srgb_to_linear(int(clean_hex[0:2], 16) / 255.0)
    g = srgb_to_linear(int(clean_hex[2:4], 16) / 255.0)
    b = srgb_to_linear(int(clean_hex[4:6], 16) / 255.0)

    l_ = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m_ = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s_ = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)

    return (
        0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_,
    )


def oklab_to_hex(L: float, a: float, b: float) -> str:
    """Convert OKLab (L, a, b) coordinates back to #rrggbb hex string."""
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.291485548 * b

    l_val = l_ * l_ * l_
    m = m_ * m_ * m_
    s = s_ * s_ * s_

    r = linear_to_srgb(4.0767416621 * l_val - 3.3077115913 * m + 0.2309699292 * s)
    g = linear_to_srgb(-1.2684380046 * l_val + 2.6097574011 * m - 0.3413193965 * s)
    bl = linear_to_srgb(-0.0041960863 * l_val - 0.7034186147 * m + 1.707614701 * s)

    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(bl * 255):02x}"


def is_light_theme(terminal_bg: str | None) -> bool:
    """Return True if the background lightness L > 0.5."""
    if not terminal_bg:
        return False
    hex_color = normalize_hex(terminal_bg)
    if not hex_color:
        return False
    return hex_to_oklab(hex_color)[0] > LIGHT_THEME_THRESHOLD


def lifted_from_terminal_bg(
    terminal_bg: str | None,
    base_lift: float = BASE_LIFT,
    nudge_a: float = 0.0,
    nudge_b: float = 0.0,
) -> str:
    """Perceptually lift/darken a color from terminal background using OKLab."""
    hex_bg = normalize_hex(terminal_bg) or "#000000"
    L, a, b = hex_to_oklab(hex_bg)
    light = L > LIGHT_THEME_THRESHOLD
    dist = (1.0 - L) if light else L
    lift = base_lift / (1.0 + dist * LIFT_DAMPING)
    target_L = L - lift if light else L + lift
    return oklab_to_hex(target_L, a + nudge_a, b + nudge_b)


def compute_adaptive_surface(terminal_bg: str | None = None, mode: str = "act") -> str:
    """Compute adaptive background for message inputs, bubbles and panels."""
    warm = mode == "plan"
    nudge = CHROMA_NUDGE if warm else -CHROMA_NUDGE
    return lifted_from_terminal_bg(terminal_bg, BASE_LIFT, nudge, nudge)


def compute_adaptive_border(terminal_bg: str | None = None) -> str:
    """Compute adaptive neutral border/rule color."""
    return lifted_from_terminal_bg(terminal_bg, RULE_BASE_LIFT, 0.0, 0.0)


def clear_palette_cache() -> None:
    """Clear cached terminal colors to allow re-querying."""
    global _CACHED_TERMINAL_COLORS
    _CACHED_TERMINAL_COLORS = None


def lerp_oklab(c1_hex: str, c2_hex: str, t: float) -> str:
    """Perceptually blend two hex colors in OKLab color space (t from 0.0 to 1.0)."""
    clean1 = normalize_hex(c1_hex) or "#000000"
    clean2 = normalize_hex(c2_hex) or "#ffffff"
    L1, a1, b1 = hex_to_oklab(clean1)
    L2, a2, b2 = hex_to_oklab(clean2)
    t_clamped = max(0.0, min(1.0, float(t)))
    return oklab_to_hex(
        L1 + (L2 - L1) * t_clamped,
        a1 + (a2 - a1) * t_clamped,
        b1 + (b2 - b1) * t_clamped,
    )


def detect_os_theme_dark() -> bool:
    """Detect whether the operating system is currently using dark mode."""
    if sys.platform == "darwin":
        try:
            import subprocess

            res = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=0.2,
            )
            return "dark" in res.stdout.strip().lower()
        except Exception:
            return True

    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return val == 0
        except Exception:
            return True

    if sys.platform.startswith("linux"):
        try:
            import subprocess

            res = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True,
                text=True,
                timeout=0.2,
            )
            return "dark" in res.stdout.strip().lower()
        except Exception:
            return True

    return True


def compute_adaptive_palette(
    terminal_bg: str | None = None,
    terminal_fg: str | None = None,
    mode: str = "act",
) -> dict[str, Any]:
    """Compute fully dynamic semantic palette for native theme based on detected BG & FG."""
    norm_bg = normalize_hex(terminal_bg)
    norm_fg = normalize_hex(terminal_fg)

    if norm_bg is None:
        os_dark = detect_os_theme_dark()
        norm_bg = "#09090b" if os_dark else "#ffffff"

    is_dark = not is_light_theme(norm_bg)

    if norm_fg is None:
        norm_fg = "#e4e4e7" if is_dark else "#18181b"

    surface = compute_adaptive_surface(norm_bg, mode=mode)
    border = compute_adaptive_border(norm_bg)
    fg_secondary = lerp_oklab(norm_fg, norm_bg, 0.25)
    fg_muted = lerp_oklab(norm_fg, norm_bg, 0.48)
    subtle = lerp_oklab(norm_fg, norm_bg, 0.30)

    tcss_vars = {
        "bg-app": "ansi_default",
        "bg-surface": surface,
        "bg-inverted": norm_fg,
        "fg-primary": norm_fg,
        "fg-secondary": fg_secondary,
        "fg-muted": fg_muted,
        "fg-inverted": norm_bg,
        "border": border,
        "bg-code": surface,
        "accent-info": "#61afef",
        "accent-warning": "#e5c07b",
        "accent-error": "#e06c75",
        "accent-success": "#98c379",
        "ansi-background": "ansi_default",
    }

    return {
        "dark": is_dark,
        "primary": norm_fg,
        "secondary": fg_secondary,
        "muted": fg_muted,
        "subtle": subtle,
        "bg_surface": surface,
        "border": border,
        "fg_primary": norm_fg,
        "fg_secondary": fg_secondary,
        "fg_muted": fg_muted,
        "fg_inverted": norm_bg,
        "bg_inverted": norm_fg,
        "tcss_vars": tcss_vars,
    }


def parse_osc_palette(resp: str | bytes) -> tuple[str | None, str | None]:
    """Parse OSC 11 (background) and OSC 10 (foreground) RGB responses."""
    resp_bytes = resp.encode("latin1", errors="ignore") if isinstance(resp, str) else resp
    bg = None
    fg = None

    bg_m = re.search(rb"11;rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", resp_bytes)
    if bg_m:
        r, g, b = (x.decode(errors="ignore") for x in bg_m.groups())
        bg = f"#{r[:2].lower()}{g[:2].lower()}{b[:2].lower()}"

    fg_m = re.search(rb"10;rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", resp_bytes)
    if fg_m:
        r, g, b = (x.decode(errors="ignore") for x in fg_m.groups())
        fg = f"#{r[:2].lower()}{g[:2].lower()}{b[:2].lower()}"

    return bg, fg


def _query_windows_palette(timeout: float) -> tuple[str | None, str | None]:
    """Query OSC 10/11 palette on Windows via msvcrt input polling."""
    import msvcrt

    sys.stdout.write("\x1b]11;?\x1b\\\x1b]10;?\x1b\\")
    sys.stdout.flush()

    resp = ""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            resp += ch
            if resp.count("\x1b\\") >= 2 or resp.count("\x07") >= 2:
                break
        else:
            time.sleep(0.005)
    return parse_osc_palette(resp)


def _query_posix_palette(timeout: float) -> tuple[str | None, str | None]:
    """Query OSC 10/11 palette on POSIX systems via termios / select."""
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_attr = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        is_tmux = bool(os.environ.get("TMUX"))
        term = os.environ.get("TERM", "").lower()
        is_screen = "screen" in term or "tmux" in term
        if is_tmux or is_screen:
            # Wrap in DCS pass-through sequence for tmux/screen
            sys.stdout.write("\x1bPtmux;\x1b\x1b]11;?\x1b\\\x1b\\\x1bPtmux;\x1b\x1b]10;?\x1b\\\x1b\\")
        else:
            sys.stdout.write("\x1b]11;?\x1b\\\x1b]10;?\x1b\\")
        sys.stdout.flush()

        resp = b""
        while select.select([fd], [], [], timeout)[0]:
            chunk = os.read(fd, 128)
            if not chunk:
                break
            resp += chunk
            if resp.count(b"\x1b\\") >= 2 or resp.count(b"\x07") >= 2:
                break
        return parse_osc_palette(resp)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attr)


def query_terminal_palette(timeout: float = 0.04) -> tuple[str | None, str | None]:
    """Query terminal for OSC 11 background and OSC 10 foreground colors cross-platform."""
    global _CACHED_TERMINAL_COLORS
    if _CACHED_TERMINAL_COLORS is not None:
        return _CACHED_TERMINAL_COLORS

    # Check COLORFGBG environment variable first (e.g. "15;0" or "0;15")
    colorfgbg = os.environ.get("COLORFGBG", "").strip()
    if colorfgbg and ";" in colorfgbg:
        parts = colorfgbg.split(";")
        bg_idx = parts[-1].strip()
        if bg_idx in ("0", "1", "2", "3", "4", "5", "6", "8"):
            _CACHED_TERMINAL_COLORS = ("#000000", "#ffffff")
            return _CACHED_TERMINAL_COLORS
        elif bg_idx in ("7", "15"):
            _CACHED_TERMINAL_COLORS = ("#ffffff", "#000000")
            return _CACHED_TERMINAL_COLORS

    # Only attempt OSC query if running in a foreground TTY session
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        _CACHED_TERMINAL_COLORS = (None, None)
        return _CACHED_TERMINAL_COLORS

    try:
        if sys.platform == "win32":
            _CACHED_TERMINAL_COLORS = _query_windows_palette(timeout)
        else:
            _CACHED_TERMINAL_COLORS = _query_posix_palette(timeout)
        return _CACHED_TERMINAL_COLORS
    except Exception:
        _CACHED_TERMINAL_COLORS = (None, None)
        return _CACHED_TERMINAL_COLORS
