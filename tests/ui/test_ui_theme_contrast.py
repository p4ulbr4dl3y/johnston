"""Theme tokens must clear WCAG 2.1 AA (P0-1) and expose an overlay token (P0-3).

Terminal UIs cannot rely on an accessibility tree, so contrast is the part of
WCAG that transfers directly: 1.4.3 (4.5:1 body text) and 1.4.11 (3:1 for the
boundaries of UI components). These tests keep ``themes.json`` honest.
"""

import json
from pathlib import Path

import pytest

from core.domain.defaults.themes import list_themes
from core.domain.policies.theme_contrast import (
    TEXT_CONTRAST_AA,
    UI_CONTRAST_AA,
    composite,
    contrast_ratio,
    meets_on_all,
)
from core.infrastructure.platform.terminal_theme import compute_adaptive_palette

THEMES_JSON = Path(__file__).resolve().parents[2] / "core" / "domain" / "defaults" / "themes.json"
TEXT_TOKENS = ("fg-primary", "fg-secondary", "fg-muted")
TERMINAL_PAIRS = [
    ("#000000", "#ffffff"),
    ("#1e1e1e", "#d4d4d4"),
    ("#282c34", "#abb2bf"),
    ("#0d1117", "#e6edf3"),
    ("#ffffff", "#000000"),
    ("#fafafa", "#18181b"),
]


def _themes():
    return [t for t in list_themes()]


@pytest.mark.parametrize("theme", _themes(), ids=lambda t: t.name)
def test_text_tokens_meet_aa(theme):
    backgrounds = [theme.tcss_vars.get("bg-app"), theme.tcss_vars.get("bg-surface")]
    for token in TEXT_TOKENS:
        color = theme.tcss_vars.get(token)
        assert color, f"{theme.name}: missing {token}"
        assert meets_on_all(color, backgrounds, TEXT_CONTRAST_AA), (
            f"{theme.name}: {token} {color} below {TEXT_CONTRAST_AA}:1 "
            f"(bg-app={contrast_ratio(color, backgrounds[0]) if str(backgrounds[0]).startswith('#') else 'ansi'}, "
            f"bg-surface={contrast_ratio(color, backgrounds[1]):.2f})"
        )


@pytest.mark.parametrize("theme", _themes(), ids=lambda t: t.name)
def test_border_meets_ui_contrast(theme):
    border = theme.tcss_vars.get("border")
    backgrounds = [theme.tcss_vars.get("bg-app"), theme.tcss_vars.get("bg-surface")]
    assert border, f"{theme.name}: missing border"
    assert meets_on_all(border, backgrounds, UI_CONTRAST_AA), (
        f"{theme.name}: border {border} below {UI_CONTRAST_AA}:1 on {backgrounds}"
    )


@pytest.mark.parametrize("theme", _themes(), ids=lambda t: t.name)
def test_theme_defines_overlay_token(theme):
    """`$bg-overlay` is referenced by app.tcss; a missing token silently falls
    back to Textual's hard-coded black scrim (wrong on light themes)."""
    assert theme.tcss_vars.get("bg-overlay"), f"{theme.name}: missing bg-overlay"


DECORATIVE_VISIBLE = 1.3  # a rule nobody can see is just broken layout


@pytest.mark.parametrize("theme", _themes(), ids=lambda t: t.name)
def test_decorative_rule_token_exists_and_stays_decorative(theme):
    """`border-subtle` is referenced by app.tcss for rules that live inside
    prose (markdown tables, `---`). It must exist on every theme, stay visible,
    and stay clearly quieter than `border` — otherwise the 3:1 component edges
    stop reading as the important ones.
    """
    subtle = theme.tcss_vars.get("border-subtle")
    border = theme.tcss_vars.get("border")
    assert subtle, f"{theme.name}: missing border-subtle"
    backgrounds = [bg for bg in (theme.tcss_vars.get("bg-app"), theme.tcss_vars.get("bg-surface"))
                   if isinstance(bg, str) and bg.startswith("#")]
    if not backgrounds:  # native/ANSI: resolved from the terminal at runtime
        pytest.skip(f"{theme.name}: background resolved by the terminal")
    ratios = [contrast_ratio(subtle, bg) for bg in backgrounds]
    assert min(ratios) >= DECORATIVE_VISIBLE, f"{theme.name}: border-subtle {subtle} invisible ({min(ratios):.2f}:1)"
    assert max(ratios) < UI_CONTRAST_AA, (
        f"{theme.name}: border-subtle {subtle} is as loud as a component border ({max(ratios):.2f}:1)"
    )
    if isinstance(border, str) and border.startswith("#"):
        assert min(ratios) < min(contrast_ratio(border, bg) for bg in backgrounds), (
            f"{theme.name}: border-subtle must stay weaker than border"
        )


@pytest.mark.parametrize("theme", _themes(), ids=lambda t: t.name)
def test_border_stays_visible_behind_modal_scrim(theme):
    """A modal paints `bg-overlay` over the app, so the dialog outline is the
    only cue for its edges — it must clear 3:1 against the *composited* scrim,
    not just against the raw background (light themes failed this at 2.4:1).
    """
    overlay = theme.tcss_vars.get("bg-overlay")
    border = theme.tcss_vars.get("border")
    assert overlay, f"{theme.name}: missing bg-overlay"
    backdrops = [
        c
        for c in (composite(overlay, theme.tcss_vars.get("bg-app")),
                  composite(overlay, theme.tcss_vars.get("bg-surface")))
        if c
    ]
    if not backdrops:  # native/ANSI: no opaque background to composite onto
        pytest.skip(f"{theme.name}: background resolved by the terminal")
    assert meets_on_all(border, backdrops, UI_CONTRAST_AA), (
        f"{theme.name}: border {border} below {UI_CONTRAST_AA}:1 against the modal scrim {backdrops}"
    )


def test_theme_entity_muted_matches_token():
    """Footer/header text colors read `Theme.muted`, not `tcss_vars.fg-muted`."""
    for theme in _themes():
        assert theme.muted == theme.tcss_vars.get("fg-muted"), theme.name


def test_markdown_code_background_is_not_the_border_token():
    """`border` is tuned for 3:1 edges; using it as a code background couples
    those two concerns (a cyan `border` would tint every code block)."""
    data = json.loads(THEMES_JSON.read_text())
    for theme in data:
        for key, value in theme.get("markdown_styles", {}).items():
            assert "on $border" not in value, f"{theme['name']}: {key} uses $border as background"


@pytest.mark.parametrize(("bg", "fg"), TERMINAL_PAIRS, ids=lambda v: v)
def test_native_palette_meets_contrast(bg, fg):
    """The ANSI/native theme derives colors from the terminal; it must still
    clear the same thresholds against both the terminal bg and its surface."""
    palette = compute_adaptive_palette(bg, fg)
    tcss = palette["tcss_vars"]
    surface = tcss["bg-surface"]
    assert contrast_ratio(tcss["fg-muted"], bg) >= TEXT_CONTRAST_AA
    assert contrast_ratio(tcss["fg-muted"], surface) >= TEXT_CONTRAST_AA
    assert contrast_ratio(tcss["border"], bg) >= UI_CONTRAST_AA
    assert contrast_ratio(tcss["border"], surface) >= UI_CONTRAST_AA
    subtle = tcss["border-subtle"]
    assert min(contrast_ratio(subtle, bg), contrast_ratio(subtle, surface)) >= DECORATIVE_VISIBLE
    assert max(contrast_ratio(subtle, bg), contrast_ratio(subtle, surface)) < UI_CONTRAST_AA
