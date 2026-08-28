"""Unit tests for terminal_theme and OKLab perceptual color math."""

from core.infrastructure.platform.terminal_theme import (
    compute_adaptive_border,
    compute_adaptive_surface,
    hex_to_oklab,
    is_light_theme,
    lifted_from_terminal_bg,
    normalize_hex,
    oklab_to_hex,
    query_terminal_palette,
)


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


def test_query_terminal_palette_fallback(monkeypatch):
    monkeypatch.setenv("COLORFGBG", "15;0")
    # Reset cached value
    import core.infrastructure.platform.terminal_theme as tt

    tt._CACHED_TERMINAL_COLORS = None
    bg, fg = query_terminal_palette()
    assert bg == "#000000"
    assert fg == "#ffffff"
