"""Unit tests for ThemeCommand and command suggestions."""

from unittest.mock import MagicMock

import pytest

from widgets.commands import ThemeCommand
from widgets.presentation.screens.theme import ThemeScreen


@pytest.mark.asyncio
async def test_theme_command_pushes_screen():
    app = MagicMock()
    app.set_app_theme = MagicMock()
    app.notify = MagicMock()

    cmd = ThemeCommand()
    assert cmd.name == "/theme"
    assert "/themes" in cmd.aliases
    assert "/colors" in cmd.aliases

    await cmd.execute(app)
    assert app.push_screen.called
    screen, callback = app.push_screen.call_args[0][0], app.push_screen.call_args[1]["callback"]
    assert isinstance(screen, ThemeScreen)

    # Trigger callback
    callback("catppuccin-mocha")
    app.set_app_theme.assert_called_once_with("catppuccin-mocha", persist=True)
    app.notify.assert_called_once()
