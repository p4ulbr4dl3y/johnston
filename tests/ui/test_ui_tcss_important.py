"""app.tcss must not lean on `!important` (P2-14).

41 `!important` declarations — most of them the global scrollbar kill — blocked
every future stylesheet or theme from overriding them. The kill is now a plain
`Widget` rule (matches every node, wins by cascade order instead of force) and
the lists that *should* scroll out-specify it.
"""

import re

import pytest

from app import JohnstonApp

from widgets.presentation.screens.theme import ThemeScreen

APP_TCSS = "app.tcss"

# The only rules allowed to keep `!important`: Textual styles the caret and the
# selection per theme (`TextArea:dark .text-area--cursor` and friends) and
# Johnston forces a true-colour caret instead of inverting the theme.
ALLOWED_IMPORTANT_SELECTORS = ("text-area--selection", "input--selection", "text-area--cursor", "input--cursor")

MAX_IMPORTANT = 8


def _rules_with_important():
    """Yield ``(selector_text, declarations)`` for every rule using `!important`."""
    css = open(APP_TCSS).read()
    # Strip comments so the doc comment mentioning !important does not count.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector, body = match.group(1).strip(), match.group(2)
        if "!important" in body:
            yield selector, body


def test_only_the_caret_and_selection_rules_use_important():
    offenders = []
    for selector, body in _rules_with_important():
        if not any(allowed in selector for allowed in ALLOWED_IMPORTANT_SELECTORS):
            offenders.append(selector.splitlines()[-1].strip())
    assert not offenders, f"unexpected !important in: {offenders}"


def test_important_count_stays_low():
    total = sum(body.count("!important") for _, body in _rules_with_important())
    assert total <= MAX_IMPORTANT, f"{total} !important declarations in app.tcss"


def test_scrollbar_kill_is_not_forced():
    """`* { ... !important }` would beat every later rule; `Widget` need not."""
    for selector, body in _rules_with_important():
        assert "scrollbar-size" not in body, f"forced scrollbar rule: {selector}"


@pytest.mark.asyncio
async def test_lists_scroll_and_prose_does_not():
    """The point of the refactor: bars on lists, none on prose or the chat."""
    from textual.widgets import OptionList

    app = JohnstonApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.5)

        chat = app.query_one("#chat-view")
        assert not chat.show_vertical_scrollbar

        app.push_screen(ThemeScreen())
        await pilot.pause(0.6)
        opt_list = app.screen.query_one(OptionList)
        assert opt_list.show_vertical_scrollbar, "theme list must still show a bar (P1-6)"
        # And the modal chrome around it stays clean.
        assert not app.screen.query_one("#modal-dialog").show_vertical_scrollbar
