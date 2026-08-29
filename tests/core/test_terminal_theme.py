import sys

import pytest

from core.infrastructure.platform.terminal_theme import (
    _cbrt,
    compute_adaptive_border,
    compute_adaptive_surface,
    hex_to_oklab,
    is_light_theme,
    lifted_from_terminal_bg,
    normalize_hex,
    oklab_to_hex,
    parse_osc_palette,
    query_terminal_palette,
)


def test_cbrt_fallback(monkeypatch):
    import core.infrastructure.platform.terminal_theme as tt

    # Direct test
    assert round(_cbrt(8.0), 4) == 2.0
    assert round(_cbrt(0.0), 4) == 0.0

    # Test without math.cbrt attribute (simulating Python 3.10)
    monkeypatch.delattr(tt.math, "cbrt", raising=False)
    assert round(tt._cbrt(27.0), 4) == 3.0
    assert round(tt._cbrt(0.0), 4) == 0.0


def test_normalize_hex():
    assert normalize_hex("#fff") == "#ffffff"
    assert normalize_hex("#000") == "#000000"
    assert normalize_hex("#123456") == "#123456"
    assert normalize_hex("#AABBCC") == "#aabbcc"
    assert normalize_hex("invalid") is None
    assert normalize_hex(None) is None


def test_hex_to_oklab_and_back():
    colors = ["#000000", "#ffffff", "#79b8ff", "#ffea7f", "#181818"]
    for hex_color in colors:
        L, a, b = hex_to_oklab(hex_color)
        reconstructed = oklab_to_hex(L, a, b)
        # Verify lightness matches expected ranges
        if hex_color == "#000000":
            assert L == 0.0
            assert reconstructed == "#000000"
        elif hex_color == "#ffffff":
            assert round(L, 2) == 1.0
            assert reconstructed == "#ffffff"
        else:
            assert reconstructed.startswith("#")
            assert len(reconstructed) == 7


def test_is_light_theme():
    assert is_light_theme("#ffffff") is True
    assert is_light_theme("#fdf6e3") is True  # Solarized light
    assert is_light_theme("#000000") is False
    assert is_light_theme("#181818") is False
    assert is_light_theme(None) is False


def test_adaptive_surface_and_border_computation():
    dark_surface = compute_adaptive_surface("#000000", mode="act")
    assert dark_surface.startswith("#")
    assert dark_surface != "#000000"

    plan_surface = compute_adaptive_surface("#000000", mode="plan")
    assert plan_surface.startswith("#")

    light_surface = compute_adaptive_surface("#ffffff", mode="act")
    assert light_surface.startswith("#")
    assert light_surface != "#ffffff"

    border = compute_adaptive_border("#181818")
    assert border.startswith("#")
    assert len(border) == 7


def test_lifted_from_terminal_bg_fallback():
    res = lifted_from_terminal_bg(None)
    assert res.startswith("#")


def test_parse_osc_palette():
    # Standard OSC 11 / 10 response format
    resp_bytes = b"\x1b]11;rgb:1e1e/1e1e/1e1e\x1b\\\x1b]10;rgb:d4d4/d4d4/d4d4\x1b\\"
    bg, fg = parse_osc_palette(resp_bytes)
    assert bg == "#1e1e1e"
    assert fg == "#d4d4d4"

    # String format
    resp_str = "\x1b]11;rgb:ffff/ffff/ffff\x07\x1b]10;rgb:0000/0000/0000\x07"
    bg_s, fg_s = parse_osc_palette(resp_str)
    assert bg_s == "#ffffff"
    assert fg_s == "#000000"

    # Empty / garbage
    bg_e, fg_e = parse_osc_palette(b"garbage")
    assert bg_e is None
    assert fg_e is None


def test_query_terminal_palette_fallback(monkeypatch):
    monkeypatch.setenv("COLORFGBG", "15;0")
    # Reset cached value
    import core.infrastructure.platform.terminal_theme as tt

    tt._CACHED_TERMINAL_COLORS = None
    bg, fg = query_terminal_palette()
    assert bg == "#000000"
    assert fg == "#ffffff"


def test_query_terminal_palette_windows_mock(monkeypatch):
    import core.infrastructure.platform.terminal_theme as tt

    monkeypatch.delenv("COLORFGBG", raising=False)
    monkeypatch.setattr(tt.sys, "platform", "win32")
    monkeypatch.setattr(tt.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(tt.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        "core.infrastructure.platform.terminal_theme._query_windows_palette",
        lambda timeout: ("#181818", "#f0f0f0"),
    )

    tt._CACHED_TERMINAL_COLORS = None
    bg, fg = query_terminal_palette()
    assert bg == "#181818"
    assert fg == "#f0f0f0"


def test_clear_palette_cache():
    import core.infrastructure.platform.terminal_theme as tt

    tt._CACHED_TERMINAL_COLORS = ("#111111", "#eeeeee")
    tt.clear_palette_cache()
    assert tt._CACHED_TERMINAL_COLORS is None


def test_lerp_oklab():
    from core.infrastructure.platform.terminal_theme import lerp_oklab

    # t=0.0 should return c1
    assert lerp_oklab("#000000", "#ffffff", 0.0) == "#000000"
    # t=1.0 should return c2
    assert lerp_oklab("#000000", "#ffffff", 1.0) == "#ffffff"
    # t=0.5 midpoint
    mid = lerp_oklab("#000000", "#ffffff", 0.5)
    assert mid.startswith("#")
    assert len(mid) == 7


def test_detect_os_theme_dark(monkeypatch):
    from core.infrastructure.platform.terminal_theme import detect_os_theme_dark

    # Fallback / generic test
    is_dark = detect_os_theme_dark()
    assert isinstance(is_dark, bool)


def test_compute_adaptive_palette_dark_and_light():
    from core.infrastructure.platform.terminal_theme import compute_adaptive_palette

    # Dark background
    dark_pal = compute_adaptive_palette(terminal_bg="#111111", terminal_fg="#eeeeee")
    assert dark_pal["dark"] is True
    assert dark_pal["fg_primary"] == "#eeeeee"
    assert dark_pal["fg_inverted"] == "#111111"
    assert "bg-surface" in dark_pal["tcss_vars"]
    assert dark_pal["tcss_vars"]["bg-app"] == "ansi_default"

    # Light background
    light_pal = compute_adaptive_palette(terminal_bg="#ffffff", terminal_fg="#000000")
    assert light_pal["dark"] is False
    assert light_pal["fg_primary"] == "#000000"
    assert light_pal["fg_inverted"] == "#ffffff"
    assert "bg-surface" in light_pal["tcss_vars"]
    assert light_pal["tcss_vars"]["bg-app"] == "ansi_default"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX termios palette query")
def test_query_posix_palette_tmux_wrapper(monkeypatch):
    import core.infrastructure.platform.terminal_theme as tt

    written = []

    class DummyStdout:
        def write(self, data):
            written.append(data)

        def flush(self):
            pass

    monkeypatch.setenv("TMUX", "1")
    monkeypatch.setattr(tt.sys, "stdout", DummyStdout())
    monkeypatch.setattr(tt.sys.stdin, "fileno", lambda: 0)
    monkeypatch.setattr("termios.tcgetattr", lambda fd: [0, 0, 0, 0, 0, 0, []])
    monkeypatch.setattr("termios.tcsetattr", lambda fd, when, attr: None)
    monkeypatch.setattr("tty.setraw", lambda fd: None)
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([0], [], []))

    responses = [b"\x1bPtmux;\x1b\x1b]11;rgb:0000/0000/0000\x1b\\\x1b\\\x1bPtmux;\x1b\x1b]10;rgb:ffff/ffff/ffff\x1b\\\x1b\\", b""]
    monkeypatch.setattr("os.read", lambda fd, n: responses.pop(0) if responses else b"")

    bg, fg = tt._query_posix_palette(0.05)
    assert any("\x1bPtmux;" in w for w in written)
    assert bg == "#000000"
    assert fg == "#ffffff"

