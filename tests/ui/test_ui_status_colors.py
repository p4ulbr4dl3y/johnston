"""Tool status dots must follow the active theme and stay legible (P1-5).

The pre-audit implementation read module constants tuned for one dark theme:
2.86:1 (success) and 2.30:1 (running) on light surfaces, and the other 20
themes were ignored entirely.
"""

import pytest

from core.domain.defaults.config import (
    COLOR_STATUS_ERROR,
    COLOR_STATUS_RUNNING,
    COLOR_STATUS_SUCCESS,
)
from core.domain.defaults.themes import list_themes
from core.domain.policies.theme_contrast import TEXT_CONTRAST_AA, contrast_ratio
from widgets.app.theme_manager import theme_manager
from widgets.utils.theme_colors import FALLBACK_SURFACE, status_color

STATE_TOKENS = (
    ("running", "accent-warning"),
    ("error", "accent-error"),
    ("success", "accent-success"),
)


@pytest.fixture(autouse=True)
def _restore_theme():
    """`set_theme` mutates a singleton; put the previous theme back."""
    previous = theme_manager._current_theme.name
    yield
    try:
        theme_manager.set_theme(previous, persist=False)
    except Exception:  # pragma: no cover - best effort cleanup
        pass


@pytest.mark.parametrize("theme", list_themes(), ids=lambda t: t.name)
def test_status_colors_clear_aa_on_every_theme(theme):
    theme_manager.set_theme(theme.name, persist=False)
    # The *adapted* palette: native/ANSI resolves colors from the terminal.
    surfaces = [
        bg
        for bg in (theme_manager.current_theme.tcss_vars.get("bg-app"),
                   theme_manager.current_theme.tcss_vars.get("bg-surface"))
        if isinstance(bg, str) and bg.startswith("#")
    ]
    if not surfaces:
        pytest.skip(f"{theme.name}: background resolved by the terminal")

    for state, _token in STATE_TOKENS:
        color = status_color(state)
        assert color.startswith("#"), f"{theme.name}: {state} resolved to {color!r}"
        for surface in surfaces:
            assert contrast_ratio(color, surface) >= TEXT_CONTRAST_AA, (
                f"{theme.name}: {state} dot {color} is {contrast_ratio(color, surface):.2f}:1 on {surface}"
            )


@pytest.mark.parametrize("theme", list_themes(), ids=lambda t: t.name)
def test_status_colors_prefer_the_theme_token(theme):
    """When a theme's own accent is already legible, it must be used verbatim —
    themes are allowed to look different, just not unreadable."""
    surface = theme.tcss_vars.get("bg-surface")
    if not isinstance(surface, str) or not surface.startswith("#"):
        pytest.skip(f"{theme.name}: surface resolved by the terminal")
    theme_manager.set_theme(theme.name, persist=False)
    surfaces = [
        bg
        for bg in (theme_manager.current_theme.tcss_vars.get("bg-app"),
                   theme_manager.current_theme.tcss_vars.get("bg-surface"))
        if isinstance(bg, str) and bg.startswith("#")
    ]
    if not surfaces:
        pytest.skip(f"{theme.name}: background resolved by the terminal")

    for state, token in STATE_TOKENS:
        token_color = theme_manager.current_theme.tcss_vars.get(token)
        if isinstance(token_color, str) and all(
            contrast_ratio(token_color, bg) >= TEXT_CONTRAST_AA for bg in surfaces
        ):
            assert status_color(state) == token_color, f"{theme.name}: {token} not honoured"


def test_light_theme_status_dots_are_not_the_dark_theme_constants():
    """The concrete failure from the audit: github-light used to paint zinc's
    dark-theme greens and ambers straight onto a near-white surface."""
    theme_manager.set_theme("github-light", persist=False)
    surface = theme_manager.current_theme.tcss_vars["bg-app"]
    for state in ("running", "error", "success"):
        color = status_color(state)
        assert contrast_ratio(color, surface) >= TEXT_CONTRAST_AA
    # The dark-theme green was 2.86:1 here; it must have been replaced.
    assert status_color("success") != COLOR_STATUS_SUCCESS
    assert status_color("running") != COLOR_STATUS_RUNNING


def test_status_color_falls_back_without_a_theme(monkeypatch):
    """No theme manager (CLI/headless rendering) must not raise, and the
    constants themselves get the same legibility treatment: on the dark fallback
    surface the old error red is only 4.43:1.
    """
    monkeypatch.setattr("widgets.utils.theme_colors.active_theme_vars", lambda: {})
    resolved = {}
    for state, constant in (("running", COLOR_STATUS_RUNNING), ("error", COLOR_STATUS_ERROR),
                            ("success", COLOR_STATUS_SUCCESS)):
        color = status_color(state)
        assert color.startswith("#")
        assert contrast_ratio(color, FALLBACK_SURFACE) >= TEXT_CONTRAST_AA
        # Either the constant already clears AA, or it was nudged — never replaced.
        assert color == constant or contrast_ratio(constant, FALLBACK_SURFACE) < TEXT_CONTRAST_AA
        resolved[state] = color
    assert resolved["running"] == COLOR_STATUS_RUNNING  # 6.9:1 on the fallback surface
    assert resolved["success"] == COLOR_STATUS_SUCCESS
