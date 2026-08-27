"""Unit tests for ThemeScreen and theme UI selection with search."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from widgets.presentation.screens.base_selection import HeaderWrapOptionList
from widgets.presentation.screens.theme import ThemeScreen


class ThemeTestApp(App):
    def compose(self) -> ComposeResult:
        yield Input(id="test-input")


@pytest.mark.asyncio
async def test_theme_screen_composition_and_search():
    app = ThemeTestApp()
    async with app.run_test() as pilot:
        screen = ThemeScreen("zinc")
        await app.push_screen(screen)
        await pilot.pause()

        # Check options loaded (21 modern themes)
        opt_list = screen.query_one(f"#{screen.option_list_id}", HeaderWrapOptionList)
        assert opt_list.option_count == 21

        # Search for "charcoal"
        search_input = screen.query_one("#modal-search-input", Input)
        search_input.value = "charcoal"
        await pilot.pause()
        assert opt_list.option_count == 1

        # Cancel
        await pilot.press("escape")
        await pilot.pause()
        assert not app.is_screen_installed(screen)
