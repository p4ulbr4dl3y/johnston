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

        # 4. Check options count (all 13 themes)
        opt_list = theme_screen.query_one(f"#{theme_screen.option_list_id}", HeaderWrapOptionList)
        assert opt_list.option_count == 13
        assert opt_list.highlighted == 0

        # 5. Navigate to Dracula (index 1) and press Enter
        await pilot.press("down")
        assert opt_list.highlighted == 1
        await pilot.press("enter")
        await pilot.pause()

        # 6. Verify modal dismissed and theme switched to Dracula
        assert not isinstance(app.screen, ThemeScreen)
        assert app.theme == "dracula"
        assert theme_manager.current_theme.name == "dracula"
        assert app.screen.styles.background.hex.upper() == "#282A36"

        # 7. Open via /themes alias
        input_widget.text = "/themes"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ThemeScreen)
        theme_screen = app.screen

        # 8. Dracula should now be highlighted (index 1)
        opt_list = theme_screen.query_one(f"#{theme_screen.option_list_id}", HeaderWrapOptionList)
        assert opt_list.highlighted == 1

        # 9. Navigate down to GitHub Dark (index 10) and select
        for _ in range(9):
            await pilot.press("down")
        assert opt_list.highlighted == 10
        await pilot.press("enter")
        await pilot.pause()

        # 10. Verify switched to GitHub Dark
        assert not isinstance(app.screen, ThemeScreen)
        assert app.theme == "github-dark"
        assert theme_manager.current_theme.name == "github-dark"
        assert app.screen.styles.background.hex.upper() == "#0D1117"

        # Restore zinc
        app.set_app_theme("zinc")
        assert app.theme == "zinc"
        assert app.screen.styles.background.hex.upper() == "#09090B"
