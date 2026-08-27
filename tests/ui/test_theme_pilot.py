"""End-to-end programmatic pilot test for /theme command and ThemeScreen modal in JohnstonApp."""

import pytest

from core.theme_manager import theme_manager
from widgets.app.app import JohnstonApp
from widgets.chat_input import ChatInput
from widgets.presentation.screens.base_selection import HeaderWrapOptionList
from widgets.presentation.screens.theme import ThemeScreen


@pytest.mark.asyncio
async def test_theme_modal_full_workflow():
    app = JohnstonApp()
    async with app.run_test() as pilot:
        # 1. Start in default Zinc
        assert app.theme == "zinc"
        assert theme_manager.current_theme.name == "zinc"

        # 2. Type /theme in chat input and submit
        input_widget = app.query_one("#message-input", ChatInput)
        input_widget.text = "/theme"
        await pilot.press("enter")
        await pilot.pause()

        # 3. Verify ThemeScreen is active modal
        assert isinstance(app.screen, ThemeScreen)
        theme_screen = app.screen

        # 4. Check options and active badge
        opt_list = theme_screen.query_one(f"#{theme_screen.option_list_id}", HeaderWrapOptionList)
        assert opt_list.option_count == 6

        # 5. Search for "dracula"
        search_input = theme_screen.query_one("#modal-search-input")
        search_input.value = "dracula"
        await pilot.pause()
        assert opt_list.option_count == 1

        # 6. Select Dracula via Enter
        await pilot.press("enter")
        await pilot.pause()

        # 7. Verify modal dismissed and theme switched to Dracula
        assert not isinstance(app.screen, ThemeScreen)
        assert app.theme == "dracula"
        assert theme_manager.current_theme.name == "dracula"

        # 8. Open via /themes alias
        input_widget.text = "/themes"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ThemeScreen)
        theme_screen = app.screen

        # 9. Search "tokyo" and select
        search_input = theme_screen.query_one("#modal-search-input")
        search_input.value = "tokyo"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        # 10. Verify switched to Tokyo Night
        assert not isinstance(app.screen, ThemeScreen)
        assert app.theme == "tokyo-night"
        assert theme_manager.current_theme.name == "tokyo-night"

        # Restore zinc
        app.set_app_theme("zinc")
        assert app.theme == "zinc"
