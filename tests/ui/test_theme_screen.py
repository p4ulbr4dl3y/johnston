"""Unit tests for ThemeScreen and theme UI selection."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from widgets.presentation.screens.base_selection import HeaderWrapOptionList
from widgets.presentation.screens.theme import ThemeScreen


class ThemeTestApp(App):
    def compose(self) -> ComposeResult:
        yield Input(id="test-input")


@pytest.mark.asyncio
async def test_theme_screen_composition():
    app = ThemeTestApp()
    async with app.run_test() as pilot:
        screen = ThemeScreen("zinc")
        await app.push_screen(screen)
        await pilot.pause()

        # Check options loaded (20 modern themes)
        opt_list = screen.query_one(f"#{screen.option_list_id}", HeaderWrapOptionList)
        assert opt_list.option_count == 20
        assert opt_list.highlighted == 0

        # Move down and select catppuccin-mocha (index 1)
        await pilot.press("down")
        assert opt_list.highlighted == 1

        # Cancel
        await pilot.press("escape")
        await pilot.pause()
        assert not app.is_screen_installed(screen)
