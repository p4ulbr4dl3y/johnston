"""End-to-end programmatic pilot test for live preview and confirm-on-enter in ThemeScreen modal."""

import pytest

from core.theme_manager import theme_manager
from widgets.app.app import JohnstonApp
from widgets.chat_input import ChatInput
from widgets.presentation.screens.theme import ThemeScreen


@pytest.mark.asyncio
async def test_theme_modal_live_preview_and_confirm():
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

        # 3. Navigate down to Catppuccin Mocha -> LIVE PREVIEW!
        await pilot.press("down")
        await pilot.pause()
        assert app.theme == "catppuccin-mocha"
        assert theme_manager.current_theme.name == "catppuccin-mocha"

        # 4. Navigate down to Catppuccin Macchiato -> LIVE PREVIEW!
        await pilot.press("down")
        await pilot.pause()
        assert app.theme == "catppuccin-macchiato"
        assert theme_manager.current_theme.name == "catppuccin-macchiato"

        # 5. Press Escape -> CANCEL & REVERT to Zinc Dark!
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ThemeScreen)
        assert app.theme == "zinc"
        assert theme_manager.current_theme.name == "zinc"
        assert app.screen.styles.background.hex[:7].upper() == "#09090B"

        # 6. Open /theme modal again
        input_widget.text = "/theme"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ThemeScreen)

        # 7. Navigate down to Catppuccin Mocha and press Enter -> CONFIRM & SAVE!
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert not isinstance(app.screen, ThemeScreen)
        assert app.theme == "catppuccin-mocha"
        assert theme_manager.current_theme.name == "catppuccin-mocha"
        assert app.screen.styles.background.hex[:7].upper() == "#1E1E2E"

        # Restore zinc
        app.set_app_theme("zinc")
        assert app.theme == "zinc"
        assert app.screen.styles.background.hex[:7].upper() == "#09090B"
