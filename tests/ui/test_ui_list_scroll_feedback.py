"""Lists must show that they scroll (P1-6).

21 themes in a 12-row viewport and 57 slash commands in a 5-row popup gave no
hint that anything existed below the fold: scrollbars were switched off
globally and no counter was rendered.
"""

import re

import pytest
from textual.css.parse import parse
from textual.css.tokenize import tokenize_values

from core.domain.defaults.themes import ZINC_DARK

APP_TCSS = "app.tcss"
LIST_SELECTORS = ("ModalScreen OptionList", "#modal-dialog OptionList", "CommandSuggestions OptionList")


def _rules():
    variables = dict(ZINC_DARK.tcss_vars)
    variables.update(
        {
            "subtle": ZINC_DARK.subtle,
            "primary": ZINC_DARK.primary,
            "secondary": ZINC_DARK.secondary,
            "muted": ZINC_DARK.muted,
        }
    )
    css = open(APP_TCSS).read()
    return list(
        parse(
            APP_TCSS,
            css,
            read_from=("app.tcss", ""),
            variables=variables,
            variable_tokens=tokenize_values(variables),
            is_default_rules=False,
        )
    )


def _selectors(rule) -> str:
    return ",".join(str(sel) for sel in rule.selector_set)


def test_lists_enable_a_vertical_scrollbar():
    matched = {}
    for rule in _rules():
        selectors = _selectors(rule)
        for target in LIST_SELECTORS:
            if target in selectors:
                style = rule.styles
                if getattr(style, "scrollbar_size_vertical", None) is not None:
                    matched[target] = int(style.scrollbar_size_vertical)
    assert matched, f"no scrollbar-size rule found for {LIST_SELECTORS}"
    for target, size in matched.items():
        assert size >= 1, f"{target}: scrollbar-size-vertical is {size}"


def test_scrollbar_is_not_hidden_by_the_global_reset():
    """`ScrollBar { display: none }` would silently undo the size rules."""
    shown = [
        rule
        for rule in _rules()
        if "ScrollBar" in _selectors(rule) and str(rule.styles.display) == "block"
    ]
    assert shown, "ScrollBar stays display:none, so no list can show one"


def test_command_popup_shows_more_three_rows():
    """The slash popup used to cap at 5 rows (3 options after the header)."""
    for rule in _rules():
        if "command-suggestions" in _selectors(rule).lower() and rule.styles.max_height is not None:
            if int(rule.styles.max_height.value) > 5:
                return
    pytest.fail("command suggestions popup max-height is still <= 5 rows")


@pytest.mark.asyncio
async def test_long_selection_list_reports_position():
    """The theme list scrolls, so its hint row carries `position/total`."""
    from textual.widgets import OptionList

    from app import JohnstonApp
    from widgets.presentation.screens.theme import ThemeScreen
    from widgets.presentation.widgets.modal_hint import ModalHint

    app = JohnstonApp()
    async with app.run_test(size=(90, 24)) as pilot:
        await pilot.pause(0.3)
        screen = ThemeScreen()
        app.push_screen(screen)
        await pilot.pause(0.4)

        opt_list = screen.query_one(OptionList)
        assert opt_list.show_vertical_scrollbar, "theme list overflows but shows no scrollbar"

        total = len(opt_list.options)
        match = re.search(rb"1/(\d+)".decode(), str(screen.query_one(ModalHint).content))
        assert match, f"no position counter in {screen.query_one(ModalHint).content!r}"
        assert match.group(1) == str(total)

        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause(0.2)
        assert f"3/{total}" in str(screen.query_one(ModalHint).content)
