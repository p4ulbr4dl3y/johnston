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
        assert app.screen.styles.background.hex.upper() == "#09090B"

        # 2. Type /theme in chat input and submit
        input_widget = app.query_one("#message-input", ChatInput)
        input_widget.text = "/theme"
        await pilot.press("enter")
        await pilot.pause()

        # 3. Verify ThemeScreen is active modal
        assert isinstance(app.screen, ThemeScreen)
        theme_screen = app.screen

        # 4. Check options count (all 20 modern themes)
        opt_list = theme_screen.query_one(f"#{theme_screen.option_list_id}", HeaderWrapOptionList)
        assert opt_list.option_count == 20
        assert opt_list.highlighted == 0

        # 5. Navigate to Catppuccin Mocha (index 1) and press Enter
        await pilot.press("down")
        assert opt_list.highlighted == 1
        await pilot.press("enter")
        await pilot.pause()

        # 6. Verify modal dismissed and theme switched to Catppuccin Mocha
        assert not isinstance(app.screen, ThemeScreen)
        assert app.theme == "catppuccin-mocha"
        assert theme_manager.current_theme.name == "catppuccin-mocha"
        assert app.screen.styles.background.hex.upper() == "#1E1E2E"

        # 7. Open via /themes alias
        input_widget.text = "/themes"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ThemeScreen)
        theme_screen = app.screen

        # 8. Catppuccin Mocha should now be highlighted (index 1)
        opt_list = theme_screen.query_one(f"#{theme_screen.option_list_id}", HeaderWrapOptionList)
        assert opt_list.highlighted == 1

        # 9. Navigate down to Kanagawa Wave (index 12) and select
        for _ in range(11):
            await pilot.press("down")
        assert opt_list.highlighted == 12
        await pilot.press("enter")
        await pilot.pause()

        # 10. Verify switched to Kanagawa Wave
        assert not isinstance(app.screen, ThemeScreen)
        assert app.theme == "kanagawa-wave"
        assert theme_manager.current_theme.name == "kanagawa-wave"
        assert app.screen.styles.background.hex.upper() == "#1F1F28"

        # Restore zinc
        app.set_app_theme("zinc")
        assert app.theme == "zinc"
        assert app.screen.styles.background.hex.upper() == "#09090B"
