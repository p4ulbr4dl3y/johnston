"""End-to-end programmatic pilot test for search, live preview, and confirm-on-enter in ThemeScreen modal."""

import pytest
from textual.widgets import Input

from core.theme_manager import theme_manager
from widgets.app.app import JohnstonApp
from widgets.chat_input import ChatInput
from widgets.presentation.screens.theme import ThemeScreen


@pytest.mark.asyncio
async def test_theme_modal_search_live_preview_and_confirm():
    app = JohnstonApp()
    async with app.run_test() as pilot:
        # 1. Start in Zinc Dark (#09090B)
        app.set_app_theme("zinc")
        assert app.theme == "zinc"
        assert app.screen.styles.background.hex[:7].upper() == "#09090B"

        # 2. Open /theme modal
        input_widget = app.query_one("#message-input", ChatInput)
        input_widget.text = "/theme"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ThemeScreen)
        theme_screen = app.screen

        # 3. Live preview on down arrow
        await pilot.press("down")
        await pilot.pause()
        assert app.theme == "charcoal"
        assert theme_manager.current_theme.name == "charcoal"

        # 4. Search for "everforest"
        search_input = theme_screen.query_one("#modal-search-input", Input)
        search_input.value = "everforest"
        await pilot.pause()

        # 5. Live preview everforest
        await pilot.press("enter")
        await pilot.pause()

        # 6. Confirm everforest
        assert not isinstance(app.screen, ThemeScreen)
        assert app.theme == "everforest"
        assert theme_manager.current_theme.name == "everforest"
        assert app.screen.styles.background.hex[:7].upper() == "#2D353B"

        # Restore zinc
        app.set_app_theme("zinc")
        assert app.theme == "zinc"
        assert app.screen.styles.background.hex[:7].upper() == "#09090B"
