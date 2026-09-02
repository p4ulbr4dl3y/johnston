"""Modal chrome regressions: scrim token (P0-3) and visible highlight (P0-4).

A modal whose scrim falls back to Textual's hard-coded black dims light themes
into grey, and a highlight row that differs from its siblings only by ``bold``
leaves keyboard users without a cursor.
"""

from pathlib import Path

import pytest
from textual.color import Color

from app import JohnstonApp
from widgets.presentation.screens.theme import ThemeScreen

REPO_ROOT = Path(__file__).resolve().parents[2]
TCSS_PATH = REPO_ROOT / "app.tcss"
TEXTUAL_DEFAULT_SCRIM = Color(0, 0, 0, 0.45)


async def _push_modal(app, pilot):
    app.push_screen(ThemeScreen())
    await pilot.pause(0.4)
    return app.screen


@pytest.mark.asyncio
async def test_modal_scrim_comes_from_theme():
    """`$bg-overlay` must resolve per theme (never Textual's default scrim)."""
    app = JohnstonApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        screen = await _push_modal(app, pilot)
        assert screen.styles.background != TEXTUAL_DEFAULT_SCRIM
        assert screen.styles.background.a >= 0.5

        app.set_app_theme("github-light", persist=False)
        await pilot.pause(0.3)
        scrim = app.screen.styles.background
        assert scrim != TEXTUAL_DEFAULT_SCRIM
        # Light themes dim toward a light neutral, not toward black.
        assert sum((scrim.r, scrim.g, scrim.b)) / 3 > 128


def test_highlight_selectors_declare_a_background():
    """Highlighted rows must not be `background: transparent` (bold-only cue).

    Also guards the dead-token class of bug: every `$variable` used by app.tcss
    has to exist on the theme, otherwise the declaration is dropped silently.
    """
    from textual.css.parse import parse
    from textual.css.tokenize import tokenize_values

    from core.domain.defaults.themes import ZINC_DARK

    variables = dict(ZINC_DARK.tcss_vars)
    variables.update(
        {
            "primary": ZINC_DARK.primary,
            "secondary": ZINC_DARK.secondary,
            "muted": ZINC_DARK.muted,
            "subtle": ZINC_DARK.subtle,
        }
    )

    checked = set()
    for rule in parse(
        "app.tcss",
        TCSS_PATH.read_text(),
        read_from=("app.tcss", ""),
        variables=variables,
        variable_tokens=tokenize_values(variables),
        is_default_rules=False,
    ):
        selectors = ",".join(str(sel) for sel in rule.selector_set)
        if "option-list--option-highlighted" not in selectors:
            continue
        background = rule.styles.background
        assert background is not None and background.a > 0, (
            f"{selectors}: highlight background is transparent (only `bold` distinguishes the cursor row)"
        )
        checked.add(selectors)
    assert checked, "no highlight rules found in app.tcss"


@pytest.mark.asyncio
async def test_theme_exposes_every_token_used_by_the_stylesheet():
    """`$subtle` and friends must resolve at runtime, not silently no-op."""
    app = JohnstonApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        variables = app.get_css_variables()
        assert "subtle" in variables, "app.tcss references $subtle but no theme defines it"
        assert "bg-overlay" in variables
